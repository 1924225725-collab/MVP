import QtQuick 2.15

Item {
    id: root
    objectName: "BrandRevealRoot"
    focus: true

    signal enterRequested()

    property real timeline: 0.0
    property real exitProgress: 0.0
    property bool introComplete: false
    property bool exiting: false
    property var particles: []

    function clamp(value, low, high) {
        return Math.max(low, Math.min(high, value))
    }

    function smooth(value) {
        var x = clamp(value, 0.0, 1.0)
        return x * x * (3.0 - 2.0 * x)
    }

    function phase(start, finish) {
        return smooth((timeline - start) / (finish - start))
    }

    function finishIntro() {
        introAnimation.stop()
        timeline = 1.0
        introComplete = true
        forceActiveFocus()
    }

    function activate() {
        if (exiting)
            return
        if (!introComplete) {
            finishIntro()
            return
        }
        exiting = true
        exitAnimation.start()
    }

    Keys.onReturnPressed: activate()
    Keys.onEnterPressed: activate()
    Keys.onEscapePressed: activate()
    Keys.onSpacePressed: activate()

    Component.onCompleted: {
        var result = []
        for (var i = 0; i < 58; ++i) {
            var seed = Math.abs(Math.sin((i + 3) * 91.731))
            var seed2 = Math.abs(Math.sin((i + 11) * 47.193))
            var seed3 = Math.abs(Math.sin((i + 19) * 17.817))
            result.push({
                px: seed,
                py: seed2,
                depth: 0.28 + seed3 * 0.72,
                drift: 0.5 + seed * 1.4,
                targetX: 0.29 + ((i * 37) % 43) / 100.0,
                targetY: 0.35 + ((i * 19) % 25) / 100.0
            })
        }
        particles = result
        particleCanvas.requestPaint()
        introAnimation.start()
        forceActiveFocus()
    }

    onTimelineChanged: particleCanvas.requestPaint()
    onWidthChanged: particleCanvas.requestPaint()
    onHeightChanged: particleCanvas.requestPaint()

    NumberAnimation {
        id: introAnimation
        target: root
        property: "timeline"
        from: 0.0
        to: 1.0
        duration: 5200
        easing.type: Easing.InOutCubic
        onFinished: {
            root.introComplete = true
            root.forceActiveFocus()
        }
    }

    NumberAnimation {
        id: exitAnimation
        target: root
        property: "exitProgress"
        from: 0.0
        to: 1.0
        duration: 720
        easing.type: Easing.InOutCubic
        onFinished: root.enterRequested()
    }

    Rectangle {
        anchors.fill: parent
        color: "#050506"
    }

    Canvas {
        id: particleCanvas
        anchors.fill: parent
        opacity: 1.0 - root.smooth(root.exitProgress)

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.clearRect(0, 0, width, height)

            var appear = root.phase(0.06, 0.22)
            var gather = root.phase(0.18, 0.43)
            var settle = root.phase(0.40, 0.62)
            var now = root.timeline * 7.0
            var coords = []

            for (var i = 0; i < root.particles.length; ++i) {
                var p = root.particles[i]
                var driftX = Math.sin(now * p.drift + i) * 10.0 * p.depth
                var driftY = Math.cos(now * 0.7 + i * 1.7) * 7.0 * p.depth
                var freeX = p.px * width + driftX
                var freeY = p.py * height + driftY
                var targetX = p.targetX * width
                var targetY = p.targetY * height
                var pull = gather * (1.0 - settle * 0.76)
                var x = freeX + (targetX - freeX) * pull
                var y = freeY + (targetY - freeY) * pull
                coords.push({x: x, y: y, depth: p.depth})
            }

            ctx.lineWidth = 0.65
            for (var a = 0; a < 24; ++a) {
                for (var b = a + 1; b < 24; ++b) {
                    var dx = coords[a].x - coords[b].x
                    var dy = coords[a].y - coords[b].y
                    var dist = Math.sqrt(dx * dx + dy * dy)
                    if (dist < 115) {
                        ctx.strokeStyle = "rgba(255,255,255," + ((1.0 - dist / 115.0) * 0.055 * appear) + ")"
                        ctx.beginPath()
                        ctx.moveTo(coords[a].x, coords[a].y)
                        ctx.lineTo(coords[b].x, coords[b].y)
                        ctx.stroke()
                    }
                }
            }

            for (var j = 0; j < coords.length; ++j) {
                var c = coords[j]
                var alpha = appear * (0.10 + c.depth * 0.42) * (1.0 - settle * 0.30)
                var radius = 0.55 + c.depth * 1.35
                ctx.fillStyle = "rgba(255,255,255," + alpha + ")"
                ctx.beginPath()
                ctx.arc(c.x, c.y, radius, 0, Math.PI * 2)
                ctx.fill()
            }

            var halo = root.phase(0.24, 0.48) * (1.0 - settle * 0.62)
            var gradient = ctx.createRadialGradient(width * 0.5, height * 0.48, 0,
                                                    width * 0.5, height * 0.48, width * 0.32)
            gradient.addColorStop(0, "rgba(255,255,255," + (halo * 0.075) + ")")
            gradient.addColorStop(1, "rgba(255,255,255,0)")
            ctx.fillStyle = gradient
            ctx.fillRect(0, 0, width, height)
        }
    }

    Item {
        id: logoStage
        width: 610
        height: 238
        transformOrigin: Item.TopLeft
        property real homeX: (root.width - width) / 2.0
        property real homeY: Math.max(92, (root.height - height) / 2.0 - 92)
        x: homeX + (22 - homeX) * root.smooth(root.exitProgress)
        y: homeY + (8 - homeY) * root.smooth(root.exitProgress)
        scale: 1.0 - 0.82 * root.smooth(root.exitProgress)

        Image {
            anchors.fill: parent
            source: "../assets/dkn_mark.svg"
            fillMode: Image.PreserveAspectFit
            opacity: root.phase(0.29, 0.53) * 0.12
            scale: 1.035
        }

        Item {
            id: logoClip
            anchors.left: parent.left
            anchors.top: parent.top
            width: parent.width * root.phase(0.27, 0.53)
            height: parent.height
            clip: true

            Image {
                width: logoStage.width
                height: logoStage.height
                source: "../assets/dkn_mark.svg"
                fillMode: Image.PreserveAspectFit
                opacity: 0.98
            }
        }

        Rectangle {
            width: 1
            height: parent.height * 0.52
            x: logoClip.width - 1
            y: parent.height * 0.22
            color: "#FFFFFF"
            opacity: root.introComplete ? 0 : root.phase(0.29, 0.50) * (1.0 - root.phase(0.50, 0.55))
        }
    }

    Item {
        id: identity
        anchors.horizontalCenter: parent.horizontalCenter
        y: logoStage.homeY + logoStage.height - 8
        width: 560
        height: 250
        opacity: 1.0 - root.smooth(root.exitProgress * 1.4)

        Item {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 360
            height: 104
            clip: true
            opacity: root.phase(0.49, 0.66)

            Image {
                width: 360
                height: 104
                source: "../assets/night_rain_signature.svg"
                fillMode: Image.PreserveAspectFit
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 112
            text: "AI Live Clipper"
            color: "#F5F5F7"
            font.family: "Segoe UI Variable Display"
            font.pixelSize: 26
            font.weight: Font.DemiBold
            font.letterSpacing: 2.2
            opacity: root.phase(0.64, 0.79)
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 158
            text: "AI 驱动的视频创作伙伴"
            color: "#A6A8AD"
            font.family: "Microsoft YaHei UI"
            font.pixelSize: 13
            font.letterSpacing: 3.0
            opacity: root.phase(0.72, 0.84)
        }
    }

    Item {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Math.max(42, parent.height * 0.075)
        width: 360
        height: 58
        opacity: root.phase(0.88, 0.97) * (1.0 - root.smooth(root.exitProgress * 1.8))

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "点击任意处进入"
            color: "#D8D8DB"
            font.family: "Microsoft YaHei UI"
            font.pixelSize: 13
            font.letterSpacing: 2.4
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 28
            text: "CLICK ANYWHERE TO ENTER"
            color: "#696C73"
            font.family: "Segoe UI Variable Text"
            font.pixelSize: 9
            font.letterSpacing: 2.1
        }
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.activate()
    }
}
