// The breathing dial in the Home scene (widgets/home_scene.py): all of
// it but the ring of ticks and the needle, which sky.frag draws under
// it. Laid out in the dial's 300-unit design square, as DialButton
// paints it; HomeScene places and scales the square over the dial
// widget (which still takes the pointer, the keys and the tooltip) and
// sets every property below from DialButton.face_state, and the
// disc's uniforms on the ShaderEffect named "disc".
import QtQuick

Item {
    id: dial
    width: 300
    height: 300
    transformOrigin: Item.TopLeft

    // The press and the swell (about the centre) and the tremble.
    property real coreScale: 1.0
    property real shake: 0.0
    property font labelFont
    property font bigFont
    property font smallFont
    // The label: [text, colour, alpha] for the one leaving and the one
    // arriving (misted); the dots: [x, y, r, colour, glow r, glow colour].
    property var labels: []
    property var dots: []
    // The readout: each digit shown, [text, x, alpha, smoke spread];
    // where the minus and "dB" go; its bump; the end labels.
    property var digits: []
    property real minusX: 0
    property real unitX: 0
    property real bump: 1.0
    property color textColour
    property color captionColour
    property color gentleColour
    property real gentleX: 52
    property color strongColour
    property real strongX: 248

    Item {
        id: core
        width: 300
        height: 300
        transform: [
            Scale {
                origin.x: 150
                origin.y: 150
                xScale: dial.coreScale
                yScale: dial.coreScale
            },
            Translate { x: dial.shake }
        ]

        ShaderEffect {
            objectName: "disc"
            anchors.fill: parent
            property vector4d faceTop
            property vector4d faceMid
            property vector4d faceEdge
            property vector4d accentRgb
            property vector4d rimRgb
            property real charge
            property vector4d focusRgba
            property vector4d glyphRgba
            property real stem
            property real unit: 1.0
            fragmentShader: "disc.frag.qsb"
        }

        Repeater {
            model: 3
            Item {
                readonly property var d: index < dial.dots.length
                                         ? dial.dots[index] : null
                visible: d !== null
                Rectangle {
                    visible: parent.d !== null && parent.d[4] > 0
                    x: parent.d ? parent.d[0] - parent.d[4] : 0
                    y: parent.d ? parent.d[1] - parent.d[4] : 0
                    width: parent.d ? 2 * parent.d[4] : 0
                    height: width
                    radius: width / 2
                    color: parent.d ? parent.d[5] : "transparent"
                }
                Rectangle {
                    x: parent.d ? parent.d[0] - parent.d[2] : 0
                    y: parent.d ? parent.d[1] - parent.d[2] : 0
                    width: parent.d ? 2 * parent.d[2] : 0
                    height: width
                    radius: width / 2
                    color: parent.d ? parent.d[3] : "transparent"
                }
            }
        }

        Repeater {
            model: 2
            SmokeText {
                readonly property var d: index < dial.labels.length
                                         ? dial.labels[index] : null
                mist: true
                shown: d !== null
                text: d ? d[0] : ""
                color: d ? d[1] : "transparent"
                alpha: d ? d[2] : 0
                font: dial.labelFont
                x: 150 - width / 2
                y: 193 - baselineOffset
            }
        }
    }

    Item {
        width: 300
        height: 300
        transform: Scale {
            origin.x: 150
            origin.y: 265
            xScale: dial.bump
            yScale: dial.bump
        }
        Text {
            text: "-"
            font: dial.bigFont
            color: dial.textColour
            x: dial.minusX
            y: 276 - baselineOffset
        }
        Repeater {
            model: 6
            SmokeText {
                readonly property var d: index < dial.digits.length
                                         ? dial.digits[index] : null
                shown: d !== null
                text: d ? d[0] : ""
                x: d ? d[1] : 0
                alpha: d ? d[2] : 0
                spread: d ? d[3] : 0
                font: dial.bigFont
                color: dial.textColour
                y: 276 - baselineOffset
            }
        }
        Text {
            text: "dB"
            font: dial.bigFont
            color: dial.textColour
            x: dial.unitX
            y: 276 - baselineOffset
        }
    }

    Text {
        text: "reduction strength"
        font: dial.smallFont
        color: dial.captionColour
        x: 150 - contentWidth / 2
        y: 294 - baselineOffset
    }
    Text {
        text: "gentle"
        font: dial.smallFont
        color: dial.gentleColour
        x: dial.gentleX - contentWidth / 2
        y: 278 - baselineOffset
    }
    Text {
        text: "strong"
        font: dial.smallFont
        color: dial.strongColour
        x: dial.strongX - contentWidth / 2
        y: 278 - baselineOffset
    }
}
