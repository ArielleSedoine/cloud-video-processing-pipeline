# Processing Workflow

## Overview

The Cloud Video Processing Pipeline follows an event-driven workflow that automatically processes uploaded media into streaming-ready assets.

Each uploaded video initiates an independent processing pipeline, enabling scalable and parallel execution across cloud-native services.

---

# End-to-End Workflow

```
             User Upload
                  │
                  ▼
       Source Cloud Storage
                  │
        Object Finalize Event
                  │
                  ▼
          Cloud Function Trigger
                  │
                  ▼
      Validate Uploaded Media
                  │
                  ▼
     Create Transcoder API Job
                  │
                  ▼
        Video Transcoding
                  │
      ┌───────────┼───────────┐
      ▼           ▼           ▼
   SD Output   HD Output   UHD Output
      │           │           │
      └───────────┼───────────┘
                  ▼
          Audio Extraction
                  ▼
      Speech-to-Text Processing
                  ▼
   Multilingual Caption Generation
                  ▼
       Thumbnail Generation
                  ▼
      DASH Manifest Generation
                  ▼
     Store Processed Assets
                  ▼
        Streaming Platform
```

---

# Step 1 — Video Upload

Users upload a video file into the source Cloud Storage bucket.

Supported media files may include common video formats such as:

- MP4
- MOV
- AVI
- MKV

The uploaded file becomes the input for the processing pipeline.

---

# Step 2 — Event Detection

Google Cloud Storage automatically emits an **Object Finalize** event when the upload completes.

This event triggers the orchestration workflow.

Responsibilities:

- Detect new uploads
- Retrieve file metadata
- Start processing

---

# Step 3 — Job Initialization

The orchestration service performs initial validation.

Tasks include:

- Verify file existence
- Validate supported format
- Generate processing identifiers
- Submit a Transcoder API job

---

# Step 4 — Video Transcoding

The Transcoder API generates multiple optimized video versions.

Generated outputs include:

| Resolution | Purpose |
|------------|---------|
| SD (480p) | Low-bandwidth streaming |
| HD (720p) | Standard playback |
| UHD (1080p) | High-quality playback |

This enables adaptive streaming based on network conditions.

---

# Step 5 — Audio Processing

After transcoding, the audio stream is extracted.

Processing includes:

- Audio extraction
- Audio normalization
- Speech recognition preparation

The resulting audio asset is used for subtitle generation.

---

# Step 6 — Caption Generation

Speech recognition converts spoken content into text.

Generated subtitle tracks include:

- English
- French
- Spanish
- Japanese
- Mandarin Chinese
- Korean

Captions are exported in WebVTT format.

---

# Step 7 — Thumbnail Generation

Representative thumbnails are generated using FFmpeg.

Typical use cases include:

- Video previews
- Content management systems
- Streaming platforms
- User interfaces

---

# Step 8 — Adaptive Streaming Assets

The workflow prepares streaming-compatible assets.

Generated files include:

- DASH manifest (.mpd)
- Video segments
- Audio streams
- Caption tracks

These assets enable adaptive bitrate streaming.

---

# Step 9 — Asset Storage

All generated media is stored in the destination storage bucket.

Typical structure:

```
videos/

    sample-video/

        SD.mp4
        HD.mp4
        UHD.mp4

        audio.ogg

        thumbnail.jpg

        manifest.mpd

        subtitles/

            en.vtt
            fr.vtt
            es.vtt
            ja.vtt
            zh.vtt
            ko.vtt
```

---

# Output Summary

For every uploaded video, the pipeline produces:

✅ SD video

✅ HD video

✅ UHD video

✅ Audio-only file

✅ Thumbnail image

✅ DASH manifest

✅ Streaming segments

✅ English captions

✅ French captions

✅ Spanish captions

✅ Japanese captions

✅ Mandarin Chinese captions

✅ Korean captions

---

# Error Handling

The workflow includes validation at each stage.

Potential failures include:

- Unsupported media format
- Corrupted uploads
- Processing timeout
- Speech recognition failure
- Storage write failure

Each processing stage operates independently, allowing failed tasks to be retried without restarting the entire workflow.

---

# Scalability

The workflow is designed for horizontal scalability.

Characteristics include:

- Independent processing jobs
- Event-driven orchestration
- Parallel execution
- Stateless services
- Automatic scaling

---

# Benefits

The processing workflow provides:

- Fully automated media processing
- Adaptive streaming preparation
- Multilingual accessibility
- Cloud-native scalability
- Modular architecture
- Fault isolation
- High availability
- Easy extensibility

---

# Future Enhancements

Potential workflow improvements include:

- Automatic language detection
- AI-powered content moderation
- Scene detection
- Video summarization
- Object recognition
- OCR for embedded text
- DRM packaging
- HLS output generation
- Multi-region processing
