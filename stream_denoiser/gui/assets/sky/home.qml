// The Vigil Home card as one Qt Quick scene (widgets/home_scene.py):
// the night sky (sky.qml, which also draws the card, the page round its
// corners and the dial's ticks), the rest of the dial over it and the
// headline. Python sets everything; nothing here runs on its own.
import QtQuick

Item {
    Loader {
        objectName: "sky"
        anchors.fill: parent
        source: "sky.qml"
    }
    HomeDial {
        objectName: "dial"
        visible: false
    }
    SmokeText {
        objectName: "headline"
        shown: false
    }
}
