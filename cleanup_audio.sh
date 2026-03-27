#!/bin/bash
# Delete audio files that have already been transcribed
cd /Users/tsenkotsenkov/youtube_transcript_extractor
for wav in audio_cache/*.wav; do
    [ -f "$wav" ] || continue
    base=$(basename "$wav" .wav)
    if [ -f "transcripts/${base}.json" ]; then
        rm "$wav"
        echo "Cleaned: $wav"
    fi
done
