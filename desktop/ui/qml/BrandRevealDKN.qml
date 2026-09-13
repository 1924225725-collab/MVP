import QtQuick
import QtQuick.Shapes

Item {
    id: root
    objectName: "BrandRevealRoot"
    focus: true

    signal enterRequested()

    // Seconds on the original 1.50 s HTML timeline.  The values below are
    // transcribed directly from DNK动画.html; do not normalize or reorder.
    property real timelineSeconds: 0.0
    property real exitProgress: 0.0
    property real signatureOpacity: 0.0
    property real productOpacity: 0.0
    property real promptOpacity: 0.0
    property bool introComplete: false
    property bool terminalReady: false
    property bool exiting: false
    property bool referenceMode: false

    readonly property var strokes: [
        {
            name: "p1", width: 10.2, start: 0.039, end: 0.334,
            path: "M 446.0 424.0 C 449.5 421.8 459.8 415.0 467.0 411.0 C 474.2 407.0 481.7 403.8 489.0 400.0 C 496.3 396.2 503.7 391.7 511.0 388.0 C 518.3 384.3 525.8 381.3 533.0 378.0 C 540.2 374.7 546.8 371.5 554.0 368.0 C 561.2 364.5 568.7 360.3 576.0 357.0 C 583.3 353.7 590.7 350.2 598.0 348.0 C 605.3 345.8 607.2 348.0 620.0 344.0 C 632.8 340.0 656.7 328.3 675.0 324.0 C 693.3 319.7 714.7 313.5 730.0 318.0 C 745.3 322.5 768.2 336.7 767.0 351.0 C 765.8 365.3 739.3 388.8 723.0 404.0 C 706.7 419.2 687.2 430.3 669.0 442.0 C 650.8 453.7 632.2 464.0 614.0 474.0 C 595.8 484.0 578.2 493.3 560.0 502.0 C 541.8 510.7 514.2 522.0 505.0 526.0"
        },
        {
            name: "p2", width: 11.1, start: 0.334, end: 0.462,
            path: "M 439.0 554.0 C 445.7 551.8 468.2 545.5 479.0 541.0 C 489.8 536.5 498.7 533.3 504.0 527.0 C 509.3 520.7 504.2 514.5 511.0 503.0 C 517.8 491.5 533.8 473.2 545.0 458.0 C 556.2 442.8 565.3 430.8 578.0 412.0 C 590.7 393.2 613.8 356.2 621.0 345.0"
        },
        {
            name: "p3", width: 15.5, start: 0.462, end: 0.603,
            path: "M 849.0 315.0 C 843.3 322.2 824.8 343.5 815.0 358.0 C 805.2 372.5 794.8 393.8 790.0 402.0 C 785.2 410.2 787.7 405.2 786.0 407.0 C 784.3 408.8 782.2 409.5 780.0 413.0 C 777.8 416.5 778.3 421.8 773.0 428.0 C 767.7 434.2 755.8 440.8 748.0 450.0 C 740.2 459.2 733.3 472.0 726.0 483.0 C 718.7 494.0 711.0 505.0 704.0 516.0 C 697.0 527.0 687.3 543.5 684.0 549.0"
        },
        {
            name: "p4", width: 11.6, start: 0.603, end: 0.783,
            path: "M 928.0 330.0 C 925.2 331.5 916.7 335.7 911.0 339.0 C 905.3 342.3 899.7 346.5 894.0 350.0 C 888.3 353.5 882.7 356.7 877.0 360.0 C 871.3 363.3 865.7 366.7 860.0 370.0 C 854.3 373.3 848.7 376.7 843.0 380.0 C 837.3 383.3 831.7 386.8 826.0 390.0 C 820.3 393.2 814.8 396.8 809.0 399.0 C 803.2 401.2 794.8 401.7 791.0 403.0 C 787.2 404.3 787.8 405.3 786.0 407.0 C 784.2 408.7 782.2 409.5 780.0 413.0 C 777.8 416.5 771.7 424.0 773.0 428.0 C 774.3 432.0 782.8 434.7 788.0 437.0 C 793.2 439.3 798.7 440.0 804.0 442.0 C 809.3 444.0 814.7 446.8 820.0 449.0 C 825.3 451.2 830.7 452.8 836.0 455.0 C 841.3 457.2 846.7 459.5 852.0 462.0 C 857.3 464.5 862.7 467.2 868.0 470.0 C 873.3 472.8 878.5 476.0 884.0 479.0 C 889.5 482.0 896.8 485.5 901.0 488.0 C 905.2 490.5 906.5 492.3 909.0 494.0 C 911.5 495.7 913.7 496.5 916.0 498.0 C 918.3 499.5 920.7 501.3 923.0 503.0 C 925.3 504.7 927.7 506.3 930.0 508.0 C 932.3 509.7 934.7 511.3 937.0 513.0 C 939.3 514.7 941.7 516.2 944.0 518.0 C 946.3 519.8 948.7 522.0 951.0 524.0 C 953.3 526.0 956.8 529.0 958.0 530.0"
        },
        {
            name: "p5", width: 12.7, start: 0.783, end: 1.011,
            path: "M 902.0 487.0 C 905.2 482.2 914.7 467.7 921.0 458.0 C 927.3 448.3 933.5 438.7 940.0 429.0 C 946.5 419.3 952.7 408.7 960.0 400.0 C 967.3 391.3 979.7 378.8 984.0 377.0 C 988.3 375.2 985.3 383.0 986.0 389.0 C 986.7 395.0 987.3 403.0 988.0 413.0 C 988.7 423.0 988.5 439.2 990.0 449.0 C 991.5 458.8 992.3 471.8 997.0 472.0 C 1001.7 472.2 1009.0 462.3 1018.0 450.0 C 1027.0 437.7 1039.2 415.5 1051.0 398.0 C 1062.8 380.5 1075.3 362.3 1089.0 345.0 C 1102.7 327.7 1121.5 306.5 1133.0 294.0 C 1144.5 281.5 1153.8 274.0 1158.0 270.0"
        }
    ]

    function clamp01(value) {
        return Math.max(0.0, Math.min(1.0, value))
    }

    function ease(value) {
        var u = clamp01(value)
        return u * u * (3.0 - 2.0 * u)
    }

    function strokeProgress(stroke) {
        return ease((timelineSeconds - stroke.start) / (stroke.end - stroke.start))
    }

    function activeStrokeIndex() {
        for (var i = 0; i < strokes.length; ++i) {
            if (timelineSeconds > strokes[i].start && timelineSeconds < strokes[i].end)
                return i
        }
        return -1
    }

    function activeStrokeProgress(index) {
        if (index < 0)
            return 0.0
        return strokeProgress(strokes[index])
    }

    function showTerminalImmediately() {
        terminalAnimation.stop()
        signatureOpacity = 1.0
        productOpacity = 1.0
        promptOpacity = 1.0
        terminalReady = true
        forceActiveFocus()
    }

    function finishIntro() {
        introAnimation.stop()
        timelineSeconds = 1.5
        introComplete = true
        referenceMode = false
        showTerminalImmediately()
    }

    function seekReference(seconds) {
        introAnimation.stop()
        terminalAnimation.stop()
        timelineSeconds = clamp01(seconds / 1.5) * 1.5
        introComplete = timelineSeconds >= 1.5
        terminalReady = false
        referenceMode = true
        signatureOpacity = 0.0
        productOpacity = 0.0
        promptOpacity = 0.0
        forceActiveFocus()
    }

    function activate() {
        if (!terminalReady || exiting)
            return
        exiting = true
        exitAnimation.start()
    }

    Keys.onPressed: function(event) {
        if (root.terminalReady) {
            root.activate()
            event.accepted = true
        }
    }

    Component.onCompleted: {
        introAnimation.start()
        forceActiveFocus()
    }

    NumberAnimation {
        id: introAnimation
        target: root
        property: "timelineSeconds"
        from: 0.0
        to: 1.5
        duration: 1500
        easing.type: Easing.Linear
        onFinished: {
            root.introComplete = true
            if (!root.referenceMode)
                terminalAnimation.start()
        }
    }

    SequentialAnimation {
        id: terminalAnimation
        PauseAnimation { duration: 120 }
        NumberAnimation {
            target: root
            property: "signatureOpacity"
            from: 0.0
            to: 1.0
            duration: 440
            easing.type: Easing.OutCubic
        }
        PauseAnimation { duration: 80 }
        NumberAnimation {
            target: root
            property: "productOpacity"
            from: 0.0
            to: 1.0
            duration: 340
            easing.type: Easing.OutCubic
        }
        PauseAnimation { duration: 110 }
        NumberAnimation {
            target: root
            property: "promptOpacity"
            from: 0.0
            to: 1.0
            duration: 360
            easing.type: Easing.OutCubic
        }
        ScriptAction {
            script: {
                root.terminalReady = true
                root.forceActiveFocus()
            }
        }
    }

    NumberAnimation {
        id: exitAnimation
        target: root
        property: "exitProgress"
        from: 0.0
        to: 1.0
        duration: 540
        easing.type: Easing.InOutCubic
        onFinished: root.enterRequested()
    }

    Rectangle {
        anchors.fill: parent
        color: "#050506"
        opacity: 1.0 - root.exitProgress
    }

    Item {
        id: scene
        anchors.fill: parent
        opacity: 1.0 - root.exitProgress
        scale: 1.0 - root.exitProgress * 0.018

        Item {
            id: stage
            width: 1536
            height: 1024
            anchors.centerIn: parent
            scale: Math.min(scene.width / width, scene.height / height)

            // HTML uses a 10 px Gaussian blur on width*2.0 strokes.  Four
            // translucent vector bands approximate that falloff consistently
            // on both Qt's GPU and software renderers.
            Repeater {
                model: root.strokes
                delegate: Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: Qt.rgba(1, 1, 1, 0.04)
                        strokeWidth: modelData.width * 5.0
                        fillColor: "transparent"
                        capStyle: ShapePath.RoundCap
                        joinStyle: ShapePath.RoundJoin
                        trim.end: root.strokeProgress(modelData)
                        PathSvg { path: modelData.path }
                    }
                }
            }

            Repeater {
                model: root.strokes
                delegate: Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: Qt.rgba(1, 1, 1, 0.06)
                        strokeWidth: modelData.width * 4.0
                        fillColor: "transparent"
                        capStyle: ShapePath.RoundCap
                        joinStyle: ShapePath.RoundJoin
                        trim.end: root.strokeProgress(modelData)
                        PathSvg { path: modelData.path }
                    }
                }
            }

            Repeater {
                model: root.strokes
                delegate: Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: Qt.rgba(1, 1, 1, 0.09)
                        strokeWidth: modelData.width * 3.0
                        fillColor: "transparent"
                        capStyle: ShapePath.RoundCap
                        joinStyle: ShapePath.RoundJoin
                        trim.end: root.strokeProgress(modelData)
                        PathSvg { path: modelData.path }
                    }
                }
            }

            Repeater {
                model: root.strokes
                delegate: Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: Qt.rgba(1, 1, 1, 0.16)
                        strokeWidth: modelData.width * 2.0
                        fillColor: "transparent"
                        capStyle: ShapePath.RoundCap
                        joinStyle: ShapePath.RoundJoin
                        trim.end: root.strokeProgress(modelData)
                        PathSvg { path: modelData.path }
                    }
                }
            }

            Repeater {
                id: inkRepeater
                model: root.strokes
                delegate: Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer

                    function pointAt(progress) {
                        return inkPath.pointAtPercent(progress)
                    }

                    ShapePath {
                        id: inkPath
                        strokeColor: "#FFFFFF"
                        strokeWidth: modelData.width * 0.92
                        fillColor: "transparent"
                        capStyle: ShapePath.RoundCap
                        joinStyle: ShapePath.RoundJoin
                        trim.end: root.strokeProgress(modelData)
                        PathSvg { path: modelData.path }
                    }
                }
            }

            Item {
                id: penLayer
                property int strokeIndex: root.activeStrokeIndex()
                property real strokeU: root.activeStrokeProgress(strokeIndex)
                property point strokePoint: {
                    var item = strokeIndex >= 0 ? inkRepeater.itemAt(strokeIndex) : null
                    return item ? item.pointAt(strokeU) : Qt.point(0, 0)
                }
                visible: strokeIndex >= 0

                Rectangle {
                    width: 32
                    height: 32
                    radius: 16
                    x: penLayer.strokePoint.x - radius
                    y: penLayer.strokePoint.y - radius
                    color: "#FFFFFF"
                    opacity: 0.70
                }

                Rectangle {
                    width: 14
                    height: 14
                    radius: 7
                    x: penLayer.strokePoint.x - radius
                    y: penLayer.strokePoint.y - radius
                    color: "#FFFFFF"
                }
            }

            Item {
                id: terminalBrand
                anchors.fill: parent
                visible: !root.referenceMode

                Image {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 572
                    width: 360
                    height: 104
                    source: "../assets/night_rain_signature.svg"
                    fillMode: Image.PreserveAspectFit
                    opacity: root.signatureOpacity
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 700
                    text: "AI Live Clipper"
                    color: "#F5F5F7"
                    font.family: "Segoe UI Variable Display"
                    font.pixelSize: 28
                    font.weight: Font.DemiBold
                    font.letterSpacing: 2.4
                    opacity: root.productOpacity
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 750
                    text: "AI 驱动的视频创作伙伴"
                    color: "#A6A8AD"
                    font.family: "Microsoft YaHei UI"
                    font.pixelSize: 14
                    font.letterSpacing: 3.0
                    opacity: root.productOpacity
                }

                Item {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 886
                    width: 420
                    height: 62
                    opacity: root.promptOpacity

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
                        y: 31
                        text: "CLICK ANYWHERE TO ENTER"
                        color: "#696C73"
                        font.family: "Segoe UI Variable Text"
                        font.pixelSize: 9
                        font.letterSpacing: 2.1
                    }
                }
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: root.terminalReady
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.activate()
    }
}
