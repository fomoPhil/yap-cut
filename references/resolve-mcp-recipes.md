# Resolve MCP call recipes for a yap cut

Exact call sequences for the `davinci-resolve` MCP server (samuelgursky/davinci-resolve-mcp),
plus the traps that return `success: true` while producing wrong output.

## Traps (read before building anything)

**`end_frame` in `create_timeline_from_clips` clip_infos is EXCLUSIVE.**
Duration = `end - start`. Treating it as inclusive leaves every clip one frame short
of its slot, which puts a **1-frame black flash at every single cut**. Nothing in the
response reveals it. `scripts/build_cut.py` already emits exclusive values.
**Always verify with `timeline.detect_gaps_overlaps` and require `gap_count: 0`.**

**`safe_set_project_settings` defaults to probe mode.** It writes, reads back, then
reverts. Pass `restore: false` to persist. Look for `"restore": true` and
`restored_value` in the response - that means nothing stuck.

**`safe_*` actions reject names not prefixed `_mcp_`** unless `allow_non_mcp_name: true`.
Affects `safe_project_create`, `safe_project_delete`, `safe_project_export`.

**Destructive actions are confirm-token gated.** `delete_timelines`, `safe_copy_grade`,
`safe_project_delete` return a token valid 300s; re-call with `confirm_token`.

**Auto-archiving clutters fast.** Many mutations silently create a
`<name>_archived_vNN` timeline. Expect roughly double the timelines you made.

**Set frame rate before creating any timeline.** Resolve locks timeline frame rate
once a timeline exists in the project.

**Transcription is not available via the API on a fresh machine.** Both
`media_pool_item.transcribe_audio` and `timeline_ai.create_subtitles` return
`success: false` in ~3ms when the speech-to-text model is not downloaded, with no
error explaining why. The download can only be triggered from the Resolve GUI
(right-click clip -> Audio Transcription -> Transcribe, accept the prompt). Until
then, transcribe externally with `scripts/prep_audio.sh`. Only the *timeline
subtitle* transcript feeds `timeline.propose_cuts`; clip-level transcription does not.

## 1. Project setup

```
project_manager   safe_project_create   {name, allow_non_mcp_name: true}
project_manager   safe_set_project_settings {
                    settings: {timelineFrameRate: "24",
                               timelineResolutionWidth: "1080",
                               timelineResolutionHeight: "1920"},
                    restore: false }
```

## 2. Import and a reference timeline

```
media_storage     import_to_pool        {items: ["/abs/path/IMG_1234.MOV"]}
media_pool        probe_media_pool      -> grab the clip id from root.clips[].id
media_pool        create_timeline_from_clips {name: "YAP raw", clip_ids: [clip_id]}
```

Check `timeline.probe_timeline_structure` for the source frame count and the audio
track count. **iPhone spatial audio produces 5 audio tracks**: A1 is the normal
stereo pair (channels 1-2), A2-A5 are the four mono spatial channels. Leaving them
enabled layers duplicate voice into the export.

```
timeline  audio_mapping_report          # confirms the channel mapping (large output)
timeline  set_track_enable {track_type: "audio", index: 2..5, enabled: false}
```

## 3. Build the cut

Feed the `clip_infos` array from `scripts/build_cut.py` straight in:

```
media_pool  create_timeline_from_clips {name: "YAP cut", clip_infos: [...]}
timeline    detect_gaps_overlaps        -> MUST be gap_count 0, overlap_count 0
timeline    get_current                 -> (end_frame - start_frame) == expected frames
```

Then mute A2-A5 again on the new timeline (track state does not carry over).

## 4. Neutral colour correction

Grading is ASC CDL only; the primary colour wheels are not exposed.
`Slope` = per-channel gain, `Offset` = lift, `Power` = gamma, plus `Saturation`.

```
timeline_item_color  safe_set_cdl {track_type: "video", track_index: 1, item_index: 0,
                                   cdl: {NodeIndex: "1", Slope: "...", Offset: "...",
                                         Power: "...", Saturation: "..."}}
```

To push it to the rest, either repeat `safe_set_cdl` per `item_index` (simple, no id
lookup, one call per clip) or copy in one call:

```
timeline  source_range_report            # video-track timeline_item_id values (big output)
timeline_item_color  safe_copy_grade {track_type:"video", track_index:1, item_index:0,
                                      target_ids: [...]}   # needs confirm_token
```

Get the CDL values from `scripts/color_correct.py measure`. Verify by rendering and
running `scripts/color_correct.py verify`, not by eye on a thumbnail.

For a quick single-frame look without rendering:

```
timeline_markers  set_current_timecode {timecode: "01:00:03:13"}
resolve_control   open_page {page: "color"}     # required, else no thumbnail
timeline_markers  get_thumbnail_image
```

## 5. Render

```
render  set_format_and_codec {format: "mp4", codec: "H264"}
render  prepare_render_job {
          target_dir: "/Users/<you>/Downloads",
          custom_name: "yap-cut",
          format: "mp4", codec: "H264",
          require_temp_target: false,          # else it insists on a temp dir
          settings: {SelectAllFrames: true, FormatWidth: 1080, FormatHeight: 1920,
                     FrameRate: 24, VideoQuality: 5000, MultiPassEncode: true,
                     AudioCodec: "aac", AudioBitDepth: 16, AudioSampleRate: 48000}}
render  start {job_ids: [job_id]}
render  get_job_status {job_id}          -> JobStatus "Complete"
```

`VideoQuality` is the video bitrate in kbps. `SelectAllFrames` must be a real
boolean, not `1`. Poll the file size until it stops changing rather than trusting
status alone, then run `scripts/finalize_export.sh` to fix the 320 kbps audio.

## 6. Captions, if asked

Timeline items have **no duration control** in this API, and `insert_title` accepts
no position or duration. So a title-track caption per clip cannot be length-matched.
Instead put a Text+ inside each clip's own Fusion comp, which inherits the clip's
length automatically:

```
timeline_item_fusion  add_comp {track_type:"video", track_index:1, item_index:N}
fusion_comp  add_tool {timeline_item:{...}, tool_type:"TextPlus", name:"Caption"}
fusion_comp  add_tool {timeline_item:{...}, tool_type:"Merge",    name:"CaptionMerge"}
fusion_comp  connect  {target_tool:"CaptionMerge", input_name:"Background", source_tool:"MediaIn1"}
fusion_comp  connect  {target_tool:"CaptionMerge", input_name:"Foreground", source_tool:"Caption"}
fusion_comp  connect  {target_tool:"MediaOut1",    input_name:"Input",      source_tool:"CaptionMerge"}
fusion_comp  bulk_set_inputs {ops: [ {timeline_item:{...}, tool_name:"Caption",
                                      input_name:"StyledText", value:"LINE ONE\nLINE TWO"}, ... ]}
```

`bulk_set_inputs` needs `timeline_item` inside **each** op, not at the top level.
Useful input ids: `StyledText`, `Font`, `Style`, `Size` (relative, ~0.055),
`Center` (Point, read/write as `{"1": x, "2": y}`; y 0.74 sits in the upper third).
Text+ default shading elements are 1 White Text, 2 Red Outline, **3 Black Shadow**,
4 Blue Border - set `SelectElement: 3` then `Enabled3: 1` for a legibility shadow.
