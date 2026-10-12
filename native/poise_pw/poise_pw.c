/*
 * Poise as a node inside the PipeWire graph.
 *
 * Same structure as PipeWire's own module-filter-chain: a capture stream
 * that is a virtual sink (media.class Audio/Sink) apps play into, and a
 * playback stream to the sound card. Both share a node group, so one
 * driver (the card) clocks them, and the playback stream is triggered
 * from the capture stream's cycle: each cycle takes the input and gives
 * the output in the same callback. Nothing can queue up in between, so
 * the delay is the one poise_core enforces and nothing else.
 *
 * The callbacks never wait on Python; inference runs in a Python thread
 * through poise_core_wait_frame()/poise_core_put_frame().
 */
#include <errno.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <pipewire/pipewire.h>
#include <spa/param/audio/format-utils.h>
#include <spa/param/latency-utils.h>
#include <spa/pod/builder.h>
#include <spa/utils/defs.h>
#include <spa/utils/result.h>

#include "poise_core.h"

#define POISE_RATE 48000u
#define POISE_CHANNELS 2u

struct poise_pw {
	poise_core *core;
	uint32_t engine_latency;

	struct pw_thread_loop *loop;
	struct pw_context *context;
	struct pw_core *pw_core;
	struct spa_hook core_listener;

	struct pw_stream *capture;
	struct pw_stream *playback;
	struct spa_hook capture_listener;
	struct spa_hook playback_listener;
	struct spa_io_position *position;

	/* Latency forwarding, as in filter-chain: [SPA_DIRECTION_INPUT] is
	 * what lies downstream (the card), set on the capture side with our
	 * own delay added, so apps see the full latency of the Poise sink. */
	struct spa_latency_info latency[2];
	struct spa_process_latency_info process_latency;

	_Atomic int capture_state;
	_Atomic int playback_state;
	_Atomic int failed;
	char error[256];
};

/* Main loop thread only; the flag is set after the message is written. */
static void set_error(struct poise_pw *p, const char *what, const char *msg)
{
	if (atomic_load(&p->failed))
		return;
	snprintf(p->error, sizeof(p->error), "%s: %s", what,
			msg ? msg : "unknown error");
	atomic_store(&p->failed, 1);
}

/* ---- latency ---------------------------------------------------------- */

static void set_process_latency(struct poise_pw *p)
{
	uint64_t total = poise_core_delay(p->core) + p->engine_latency;

	spa_zero(p->process_latency);
	p->process_latency.ns = (int64_t)(total * SPA_NSEC_PER_SEC / POISE_RATE);
}

static void update_latency(struct poise_pw *p, enum spa_direction direction)
{
	struct pw_stream *s = direction == SPA_DIRECTION_OUTPUT ?
		p->playback : p->capture;
	struct spa_latency_info latency;
	uint8_t buffer[1024];
	struct spa_pod_builder b;
	const struct spa_pod *params[2];

	if (s == NULL)
		return;
	spa_pod_builder_init(&b, buffer, sizeof(buffer));
	latency = p->latency[direction];
	spa_process_latency_info_add(&p->process_latency, &latency);
	params[0] = spa_latency_build(&b, SPA_PARAM_Latency, &latency);
	params[1] = spa_process_latency_build(&b, SPA_PARAM_ProcessLatency,
			&p->process_latency);
	pw_stream_update_params(s, params, 2);
}

static void param_changed(void *data, uint32_t id, const struct spa_pod *param)
{
	struct poise_pw *p = data;
	struct spa_latency_info latency;

	if (id != SPA_PARAM_Latency || param == NULL)
		return;
	if (spa_latency_parse(param, &latency) < 0)
		return;
	if (latency.direction != SPA_DIRECTION_INPUT &&
	    latency.direction != SPA_DIRECTION_OUTPUT)
		return;
	p->latency[latency.direction] = latency;
	update_latency(p, latency.direction);
}

/* Runs on the main loop after the realtime thread raised the delay. */
static int do_latency_changed(struct spa_loop *loop, bool async, uint32_t seq,
		const void *data, size_t size, void *user_data)
{
	struct poise_pw *p = user_data;

	set_process_latency(p);
	update_latency(p, SPA_DIRECTION_INPUT);
	update_latency(p, SPA_DIRECTION_OUTPUT);
	return 0;
}

/* ---- realtime processing ---------------------------------------------- */

static void capture_process(void *data)
{
	struct poise_pw *p = data;
	struct pw_buffer *b;

	if (pw_stream_trigger_process(p->playback) < 0) {
		/* Output not ready yet: recycle the input, like filter-chain.
		 * Neither position moves, so the delay is unaffected. */
		while ((b = pw_stream_dequeue_buffer(p->capture)) != NULL)
			pw_stream_queue_buffer(p->capture, b);
		poise_core_count_trigger_fail(p->core);
	}
}

static void playback_process(void *data)
{
	struct poise_pw *p = data;
	struct pw_buffer *b;
	struct spa_buffer *buf;
	float *out[POISE_MAX_PLANES];
	uint32_t i, n_out = 0, n_in = 0, n;

	/* Every queued input buffer, in order: input is never skipped. */
	while ((b = pw_stream_dequeue_buffer(p->capture)) != NULL) {
		const float *in[POISE_MAX_PLANES];
		uint32_t planes = 0;

		buf = b->buffer;
		n = UINT32_MAX;
		for (i = 0; i < buf->n_datas && planes < POISE_MAX_PLANES; i++) {
			struct spa_data *d = &buf->datas[i];
			uint32_t off, size;

			if (d->data == NULL || d->chunk == NULL)
				continue;
			off = SPA_MIN(d->chunk->offset, d->maxsize);
			size = SPA_MIN(d->chunk->size, d->maxsize - off);
			in[planes++] = SPA_PTROFF(d->data, off, const float);
			n = SPA_MIN(n, size / (uint32_t)sizeof(float));
		}
		if (planes > 0 && n != UINT32_MAX && n > 0) {
			poise_core_input(p->core, in, planes, n);
			n_in += n;
		}
		pw_stream_queue_buffer(p->capture, b);
	}

	if ((b = pw_stream_dequeue_buffer(p->playback)) == NULL)
		return; /* the next cycle's lead check absorbs the input */
	buf = b->buffer;

	/* How much to give: what the output adapter asks for; else what
	 * came in; else one graph cycle (only valid at our rate). */
	if (b->requested > 0)
		n_out = (uint32_t)SPA_MIN(b->requested, (uint64_t)UINT32_MAX);
	else if (n_in > 0)
		n_out = n_in;
	else if (p->position != NULL &&
		 p->position->clock.rate.denom == POISE_RATE)
		n_out = (uint32_t)p->position->clock.duration;

	n = 0;
	for (i = 0; i < buf->n_datas && n < POISE_MAX_PLANES; i++) {
		struct spa_data *d = &buf->datas[i];

		if (d->data == NULL)
			continue;
		out[n++] = d->data;
		n_out = SPA_MIN(n_out, d->maxsize / (uint32_t)sizeof(float));
	}
	if (n > 0 && n_out > 0 &&
	    poise_core_output(p->core, out, n, n_out) && p->loop != NULL)
		pw_loop_invoke(pw_thread_loop_get_loop(p->loop),
				do_latency_changed, 0, NULL, 0, false, p);
	if (n == 0)
		n_out = 0;
	for (i = 0; i < buf->n_datas; i++) {
		struct spa_data *d = &buf->datas[i];

		if (d->chunk == NULL)
			continue;
		d->chunk->offset = 0;
		d->chunk->stride = sizeof(float);
		d->chunk->size = n_out * sizeof(float);
	}
	b->size = n_out;
	pw_stream_queue_buffer(p->playback, b);
}

/* ---- stream and core events ------------------------------------------- */

static void capture_state_changed(void *data, enum pw_stream_state old,
		enum pw_stream_state state, const char *error)
{
	struct poise_pw *p = data;

	atomic_store(&p->capture_state, (int)state);
	if (state == PW_STREAM_STATE_ERROR)
		set_error(p, "Poise sink", error);
}

static void playback_state_changed(void *data, enum pw_stream_state old,
		enum pw_stream_state state, const char *error)
{
	struct poise_pw *p = data;

	atomic_store(&p->playback_state, (int)state);
	if (state == PW_STREAM_STATE_ERROR)
		set_error(p, "Poise output", error);
}

static void playback_io_changed(void *data, uint32_t id, void *area, uint32_t size)
{
	struct poise_pw *p = data;

	if (id == SPA_IO_Position)
		p->position = area;
}

static const struct pw_stream_events capture_events = {
	PW_VERSION_STREAM_EVENTS,
	.state_changed = capture_state_changed,
	.param_changed = param_changed,
	.process = capture_process,
};

static const struct pw_stream_events playback_events = {
	PW_VERSION_STREAM_EVENTS,
	.state_changed = playback_state_changed,
	.io_changed = playback_io_changed,
	.param_changed = param_changed,
	.process = playback_process,
};

static void core_error(void *data, uint32_t id, int seq, int res, const char *message)
{
	struct poise_pw *p = data;

	if (id == PW_ID_CORE && res == -EPIPE)
		set_error(p, "PipeWire", "connection lost");
}

static const struct pw_core_events core_events = {
	PW_VERSION_CORE_EVENTS,
	.error = core_error,
};

/* ---- lifecycle -------------------------------------------------------- */

void poise_pw_destroy(struct poise_pw *p);

static const struct spa_pod *format_param(struct spa_pod_builder *b)
{
	struct spa_audio_info_raw info;

	spa_zero(info);
	info.format = SPA_AUDIO_FORMAT_F32P;
	info.rate = POISE_RATE;
	info.channels = POISE_CHANNELS;
	info.position[0] = SPA_AUDIO_CHANNEL_FL;
	info.position[1] = SPA_AUDIO_CHANNEL_FR;
	return spa_format_audio_raw_build(b, SPA_PARAM_EnumFormat, &info);
}

static struct pw_properties *common_props(const char *group, uint32_t quantum)
{
	struct pw_properties *props = pw_properties_new(
			PW_KEY_MEDIA_TYPE, "Audio",
			PW_KEY_APP_NAME, "Poise",
			PW_KEY_NODE_GROUP, group,
			PW_KEY_NODE_LINK_GROUP, group,
			PW_KEY_NODE_VIRTUAL, "true",
			SPA_KEY_AUDIO_POSITION, "FL,FR",
			NULL);

	if (props != NULL && quantum > 0)
		pw_properties_setf(props, PW_KEY_NODE_LATENCY, "%u/%u",
				quantum, POISE_RATE);
	return props;
}

/*
 * Create the Poise sink and its output stream and start them.
 *
 * node_name/description: the virtual sink apps play into.
 * target: sink to play to (node.name), or NULL/"" for the default.
 * frame, engine_latency, quantum, margin, fade, dry_gain: see poise_core.h.
 * Returns NULL with a message in err on failure.
 */
struct poise_pw *poise_pw_new(const char *node_name, const char *description,
		const char *target, uint32_t frame, uint32_t engine_latency,
		uint32_t quantum, uint32_t margin, uint32_t fade, float dry_gain,
		char *err, size_t errlen)
{
	struct poise_pw *p;
	struct pw_properties *cprops, *pprops;
	uint8_t buffer[1024];
	struct spa_pod_builder b;
	const struct spa_pod *params[1];
	char group[64], out_name[256], out_desc[256];
	int res;

	pw_init(NULL, NULL);

	p = calloc(1, sizeof(*p));
	if (p == NULL) {
		snprintf(err, errlen, "out of memory");
		return NULL;
	}
	p->engine_latency = engine_latency;
	p->latency[SPA_DIRECTION_INPUT] = SPA_LATENCY_INFO(SPA_DIRECTION_INPUT);
	p->latency[SPA_DIRECTION_OUTPUT] = SPA_LATENCY_INFO(SPA_DIRECTION_OUTPUT);
	p->core = poise_core_new(frame, engine_latency, quantum, margin, fade, dry_gain);
	if (p->core == NULL) {
		snprintf(err, errlen, "invalid frame/fade (%u/%u) or out of memory",
				frame, fade);
		free(p);
		return NULL;
	}
	set_process_latency(p);

	p->loop = pw_thread_loop_new("poise-pw", NULL);
	if (p->loop == NULL) {
		snprintf(err, errlen, "cannot create PipeWire loop: %s", strerror(errno));
		goto error;
	}
	pw_thread_loop_lock(p->loop);
	if (pw_thread_loop_start(p->loop) < 0) {
		pw_thread_loop_unlock(p->loop);
		snprintf(err, errlen, "cannot start PipeWire loop");
		goto error;
	}
	p->context = pw_context_new(pw_thread_loop_get_loop(p->loop), NULL, 0);
	if (p->context == NULL) {
		pw_thread_loop_unlock(p->loop);
		snprintf(err, errlen, "cannot create PipeWire context: %s", strerror(errno));
		goto error;
	}
	p->pw_core = pw_context_connect(p->context, NULL, 0);
	if (p->pw_core == NULL) {
		pw_thread_loop_unlock(p->loop);
		snprintf(err, errlen, "cannot connect to PipeWire: %s", strerror(errno));
		goto error;
	}
	pw_core_add_listener(p->pw_core, &p->core_listener, &core_events, p);

	snprintf(group, sizeof(group), "poise-%d", (int)getpid());
	snprintf(out_name, sizeof(out_name), "%s.output", node_name);
	snprintf(out_desc, sizeof(out_desc), "%s output", description);

	cprops = common_props(group, quantum);
	pprops = common_props(group, quantum);
	if (cprops == NULL || pprops == NULL) {
		pw_properties_free(cprops);
		pw_properties_free(pprops);
		pw_thread_loop_unlock(p->loop);
		snprintf(err, errlen, "out of memory");
		goto error;
	}
	pw_properties_set(cprops, PW_KEY_MEDIA_CLASS, "Audio/Sink");
	pw_properties_set(cprops, PW_KEY_NODE_NAME, node_name);
	pw_properties_set(cprops, PW_KEY_NODE_DESCRIPTION, description);
	pw_properties_set(pprops, PW_KEY_MEDIA_CLASS, "Stream/Output/Audio");
	pw_properties_set(pprops, PW_KEY_MEDIA_CATEGORY, "Playback");
	pw_properties_set(pprops, PW_KEY_MEDIA_NAME, description);
	pw_properties_set(pprops, PW_KEY_NODE_NAME, out_name);
	pw_properties_set(pprops, PW_KEY_NODE_DESCRIPTION, out_desc);
	if (target != NULL && target[0] != '\0')
		pw_properties_set(pprops, PW_KEY_TARGET_OBJECT, target);

	p->capture = pw_stream_new(p->pw_core, description, cprops);
	p->playback = pw_stream_new(p->pw_core, out_desc, pprops);
	if (p->capture == NULL || p->playback == NULL) {
		pw_thread_loop_unlock(p->loop);
		snprintf(err, errlen, "cannot create streams: %s", strerror(errno));
		goto error;
	}
	pw_stream_add_listener(p->capture, &p->capture_listener, &capture_events, p);
	pw_stream_add_listener(p->playback, &p->playback_listener, &playback_events, p);

	spa_pod_builder_init(&b, buffer, sizeof(buffer));
	params[0] = format_param(&b);
	res = pw_stream_connect(p->capture, PW_DIRECTION_INPUT, PW_ID_ANY,
			PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS |
			PW_STREAM_FLAG_RT_PROCESS | PW_STREAM_FLAG_ASYNC,
			params, 1);
	if (res >= 0) {
		spa_pod_builder_init(&b, buffer, sizeof(buffer));
		params[0] = format_param(&b);
		res = pw_stream_connect(p->playback, PW_DIRECTION_OUTPUT, PW_ID_ANY,
				PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS |
				PW_STREAM_FLAG_RT_PROCESS | PW_STREAM_FLAG_TRIGGER,
				params, 1);
	}
	if (res >= 0) {
		update_latency(p, SPA_DIRECTION_INPUT);
		update_latency(p, SPA_DIRECTION_OUTPUT);
	}
	pw_thread_loop_unlock(p->loop);
	if (res < 0) {
		snprintf(err, errlen, "cannot connect streams: %s", spa_strerror(res));
		goto error;
	}
	return p;

error:
	poise_pw_destroy(p);
	return NULL;
}

void poise_pw_destroy(struct poise_pw *p)
{
	if (p == NULL)
		return;
	if (p->core != NULL)
		poise_core_stop(p->core);
	if (p->loop != NULL) {
		pw_thread_loop_lock(p->loop);
		if (p->capture != NULL)
			pw_stream_destroy(p->capture);
		if (p->playback != NULL)
			pw_stream_destroy(p->playback);
		p->capture = p->playback = NULL;
		if (p->pw_core != NULL)
			pw_core_disconnect(p->pw_core);
		p->pw_core = NULL;
		pw_thread_loop_unlock(p->loop);
		pw_thread_loop_stop(p->loop);
	}
	if (p->context != NULL)
		pw_context_destroy(p->context);
	if (p->loop != NULL)
		pw_thread_loop_destroy(p->loop);
	poise_core_free(p->core);
	free(p);
}

poise_core *poise_pw_core(struct poise_pw *p)
{
	return p->core;
}

/* Stream states (pw_stream_state: -1 error, 0 unconnected, 1 connecting,
 * 2 paused, 3 streaming). Returns 1 and fills err once anything failed. */
int poise_pw_status(struct poise_pw *p, int *capture_state, int *playback_state,
		char *err, size_t errlen)
{
	*capture_state = atomic_load(&p->capture_state);
	*playback_state = atomic_load(&p->playback_state);
	if (!atomic_load(&p->failed))
		return 0;
	snprintf(err, errlen, "%s", p->error);
	return 1;
}

const char *poise_pw_library_version(void)
{
	return pw_get_library_version();
}
