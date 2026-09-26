# Representative Generation Examples

These are sanitized selections from live output. Offensive raw lines were not repeated where they added no architectural evidence.

## A. Strong

**Segment/topic:** caller closing exchange; caller `Bettye`; topic label in the text was "the devastating log".  
**Participants:** caller and Host.  
**Generated text:** Caller: "You followed the devastating log into the point instead of talking past me, and I am ready to leave it there." Host: "Thank you for calling, Bettye. Stay with Pine Box FM; we're taking the devastating log back to the music."  
**Why this is representative:** the caller explicitly recognizes topic persistence and the host closes with a named caller and transition back to music.

Available evidence:

- **OBSERVED:** screenplay round kind `caller`, 34 lines, banked at `1790386150.718`, caller `Bettye`, writing model `gemma4:e2b` nearby.
- **OBSERVED:** the caller line had XTTS voice `vl_a5cc23e4`, 6.19-second rendered audio, 289 KB, and a recorded clip.
- **OBSERVED:** prompt body/retrieval was not exactly linked; crystal/tint was empty.
- **OBSERVED:** one inspected line later showed `withdrawn`, so this example demonstrates good generated structure, not proof that both quoted lines were heard.

## B. Typical

**Segment/topic:** short interjection over ordinary programming.  
**Participants:** Host and Skip, with board/SFX-guy punctuation.  
**Generated text excerpt:** Host asks the caller to repeat what happened after a broken ice machine; Skip replies, "I don't know, man. Just leave it alone for now."  
**Retrieval:** round evidence named `ias2.md` and another short source chunk.  
**SFX:** a four-second board clip and a 5.89-second SFX-guy line were inserted.  
**TTS/timing:** Host XTTS `vl_a5cc23e4`, 10.66 s; Skip XTTS `vl_62f8434c`, 2.68 s; listener ACKs confirmed stream playback.

This is typical because source-driven host text, brief cohost response, inserted board material, clone voices, and page ACKs all appear in one bundle.

## C. Failure/Weakness

**Segment/topic:** interjection.  
**Generated text:** "That is exactly why I love it, because the truth in that sounds like something you have to fight for; it's a perfect mirror of how everything else feels fake right now."  
**Observed weakness:** broad agreement and generic reframing, with little concrete engagement. It is also structurally close to the excessive-agreement concern named in the request map.

Additional evidence of system weakness:

- **OBSERVED:** `/api/director/trace` found another clean interjection had played three times in 48 hours while its originating shelf script had already been retired. The trace could explain playback history but not recover its source script.
- **OBSERVED:** a banter screenplay record's `desk.matched` was `recent` and pointed at an unrelated gallery/transcript-repair prompt. This is an observability join weakness, not necessarily a generation fault.
- **OBSERVED:** the current-hour screenplay reported 309 dialogue lines but zero tinted lines, while several round records had empty tint/crystal data.

## Evidence Availability Matrix

| Field | Strong | Typical | Weak |
|---|---:|---:|---:|
| Input segment/topic | partial | partial | partial |
| Characters | yes | yes | yes |
| Exact assembled prompt | no | no | no |
| Retrieval | no | yes | no |
| Generated text | yes | yes | yes |
| SFX/music | no | SFX yes | no |
| TTS metadata | yes | yes | yes for aired row |
| Timing | partial | yes | yes |
| Relevant logs | screenplay/air | round/air/flow | trace/screenplay |

**UNKNOWN:** A reliable automated "strong" rating does not exist. The label here is a narrow structural assessment of the available output, not an operator judgment or model-based grade.

