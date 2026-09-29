import QtQuick
import QtMultimedia

Item {
    id: root
    property var descriptor: ({})
    property var playback: descriptor.playback || ({})
    property url source: descriptor.path || ""
    property string sourceType: descriptor.source_type || "image"
    property bool autoplay: playback.autoplay !== false
    property bool loop: playback.loop !== false
    property real playbackRate: playback.playback_rate || 1.0
    property real startTimeSeconds: playback.start_time_seconds || 0.0
    property real endTimeSeconds: playback.end_time_seconds ?? -1.0
    property bool muted: playback.muted !== false
    property string synchronization: playback.synchronization || "timeline"
    property real frameRate: playback.frame_rate || 24.0
    property int sequenceStart: playback.sequence_start || 0
    property int sequenceEnd: playback.sequence_end || sequenceStart
    property int sequencePadding: playback.sequence_padding || 4
    property real timelineSeconds: 0.0
    property bool timelinePlaying: false
    property bool animated: sourceType !== "image"
    property alias mediaItem: mediaLoader

    function mediaFrame() {
        return Math.max(0, Math.floor(Math.max(0, timelineSeconds - startTimeSeconds) * frameRate * playbackRate))
    }

    function videoPositionMs() {
        let elapsed = Math.max(0, (timelineSeconds - startTimeSeconds) * playbackRate)
        if (endTimeSeconds > startTimeSeconds) {
            let duration = endTimeSeconds - startTimeSeconds
            elapsed = loop ? elapsed % duration : Math.min(duration, elapsed)
        }
        return Math.max(0, (startTimeSeconds + elapsed) * 1000)
    }

    function paddedFrame(value, padding) {
        let result = String(Math.max(0, value))
        while (result.length < padding)
            result = "0" + result
        return result
    }

    function sequenceSource() {
        let count = Math.max(1, sequenceEnd - sequenceStart + 1)
        let offset = loop ? mediaFrame() % count : Math.min(count - 1, mediaFrame())
        let frame = sequenceStart + offset
        let result = source.toString()
        let hashes = ""
        for (let index = 0; index < sequencePadding; ++index)
            hashes += "#"
        if (result.indexOf(hashes) >= 0)
            return result.replace(hashes, paddedFrame(frame, sequencePadding))
        let encodedHashes = ""
        for (let encodedIndex = 0; encodedIndex < sequencePadding; ++encodedIndex)
            encodedHashes += "%23"
        if (result.indexOf(encodedHashes) >= 0)
            return result.replace(encodedHashes, paddedFrame(frame, sequencePadding))
        return result.replace(/%25?0[0-9]+d/, paddedFrame(frame, sequencePadding))
    }

    width: Math.max(1, mediaLoader.item ? mediaLoader.item.implicitWidth : 1)
    height: Math.max(1, mediaLoader.item ? mediaLoader.item.implicitHeight : 1)
    visible: animated

    Loader {
        id: mediaLoader
        anchors.fill: parent
        active: root.animated && !root.descriptor.deferred && root.source.toString().length > 0
        sourceComponent: root.sourceType === "video" ? videoComponent
            : (root.sourceType === "image_sequence" ? sequenceComponent : animatedImageComponent)
    }

    Component {
        id: animatedImageComponent
        AnimatedImage {
            id: animatedImage
            source: root.source
            playing: root.autoplay && root.synchronization === "realtime"
            speed: root.playbackRate
            fillMode: Image.Stretch
            cache: true
            Connections {
                target: root
                function onTimelineSecondsChanged() {
                    if (root.synchronization === "timeline")
                        animatedImage.currentFrame = animatedImage.frameCount > 0
                            ? root.mediaFrame() % animatedImage.frameCount : root.mediaFrame()
                }
            }
        }
    }

    Component {
        id: sequenceComponent
        Image {
            source: root.sequenceSource()
            fillMode: Image.Stretch
            asynchronous: true
            cache: true
        }
    }

    Component {
        id: videoComponent
        Item {
            implicitWidth: videoOutput.sourceRect.width > 0 ? videoOutput.sourceRect.width : 1
            implicitHeight: videoOutput.sourceRect.height > 0 ? videoOutput.sourceRect.height : 1

            VideoOutput {
                id: videoOutput
                anchors.fill: parent
                fillMode: VideoOutput.Stretch
            }
            AudioOutput {
                id: silentAudio
                muted: root.muted
            }
            MediaPlayer {
                id: player
                source: root.source
                videoOutput: videoOutput
                audioOutput: silentAudio
                playbackRate: root.playbackRate
                loops: root.loop ? -1 : 1
                onMediaStatusChanged: {
                    if (mediaStatus === MediaPlayer.LoadedMedia) {
                        position = root.synchronization === "timeline"
                            ? root.videoPositionMs() : Math.max(0, root.startTimeSeconds * 1000)
                        if (root.autoplay && root.synchronization === "realtime")
                            play()
                    }
                }
                onPositionChanged: {
                    if (root.synchronization !== "timeline" && root.endTimeSeconds > root.startTimeSeconds && position >= root.endTimeSeconds * 1000) {
                        if (root.loop) {
                            position = root.startTimeSeconds * 1000
                            play()
                        } else {
                            pause()
                        }
                    }
                }
            }
            Connections {
                target: root
                function onTimelineSecondsChanged() {
                    if (root.synchronization === "timeline") {
                        player.pause()
                        player.position = root.videoPositionMs()
                    }
                }
            }
        }
    }
}
