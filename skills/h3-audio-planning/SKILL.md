---
name: h3-audio-planning
description: Write coherent audio descriptions inside MiniMax H3 prompts from user intent, media evidence and the planned action. Coordinate speech, source audio, ambience, effects and background music without generating audio files or adding model calls.
---

# H3 Audio Planning

Design audible content in the caller's existing H3 response. Do not add a schema, separate director, tool call or audio-generation service. Follow the supplied official H3 format. Use the existing plan only where it helps; express the result as concise, concrete English, retaining original spoken words and language.

## Choose the audible focus, not a default soundtrack

Respect explicit sound, silence, dialogue, source-reuse and timing instructions. For incomplete requests, develop suitable sound from the intended action and style; do not confuse designed sound with something actually heard in the reference. Visual evidence alone cannot establish source music, lyrics, accents or exact beats.

Decide what the audience should hear foremost: a conversation, singing, dance music, a meaningful contact, an environment, or a designed rhythmic texture. Supporting layers should leave that focus intelligible. This is not a rule that everything must be quiet: energetic edits and stylized action can legitimately need forceful music and effects.

Do not introduce a narrator to read a title, brand label or visual description. Unless requested or established by the authorized source relationship, do not add intelligible speech or lyrics. Keep necessary expressive laughter, breath and exertion tied to the performance; do not turn a brief reaction into a continuous vocal loop. A vocal choir or sample is a deliberate musical choice, not an automatic consequence of “cinematic”. Preserve requested vocals; do not globally replace them with instrumental music.

## Resolve source use before composing new sound

Distinguish copying a signal, referencing its timbre/style/rhythm, newly designing sound, and omitting sound. Honor authorized reuse instead of replacing it with a generic score. A motion-only reference does not automatically authorize its soundtrack.

An `<Audio N>` may denote a supplied audio file OR an enabled synchronized track from a reference video. Use the supplied mapping and actual service capability; video and audio numbering are independent. A video containing audio does not automatically enable reuse. If provenance or capability is unknown, retain the intended relationship as unresolved in existing uncertainty fields rather than inventing a binding, lyrics, copy interval or claim of verified playback. Do not demand a separate file when an enabled video track is genuinely supported.

For known speech/singing, put speaker identity, delivery and onset/offset in the shot, and exact words in the official `<d>[Language] ...</d>` form. Keep visible text distinct from spoken content. Referencing a voice timbre does not copy its original words. Do not guess missing transcripts or replace requested singing with wordless vocals just because perception lacked audio.

## Write musical behavior rather than adjective piles

When a new score is appropriate, describe a coherent combination of musical texture/instrumentation, perceived tempo or rhythmic feel, and meaningful dynamic development. Select distinguishing features, not an inventory of instruments. “Premium” alone is not audible direction; neither is it always slow piano or deep sub-bass.

Use one continuous musical idea when the scene supports it. Change texture or intensity when the story, action or authorized edit motivates it, not automatically at every shot. A brisk visual performance should not acquire a slow score merely because the style is elegant. Exact BPM, key and instrumentation are optional unless supplied; do not fabricate measured reference tempo.

If the existing pulse, source soundtrack or physical scene already carries the intended sound, an additional score is unnecessary. `non_diegetic_music: N/A` means no audience-only score, not total silence. Conversely, preserve music when it is central to dancing, musical editing or the user's request.

## Give effects a trigger and a place

Attach important physical sounds to the action that causes them: contact, release, motion or impact. Continue them across cuts only while their source action continues; let natural decay finish without inventing new contacts. Camera motion itself need not make a whoosh. Stylized UI, fantasy and editorial effects are valid when they fit the requested treatment; they are designed effects, not observed acoustics.

Avoid assigning the same low drone to both ambience and score as though it were two independent layers. Where several layers are warranted, describe their relative prominence and different roles. Do not force wind, room hum, cloth rustle or footsteps into every scene.

## Use H3 sections consistently

- In the shot description, place dialogue, singing, diegetic music and the meaningful starts, stops and synchronized events. Do not add shots solely to accommodate audio.
- In `overall_soundscape`, summarize environment, physical sounds and non-verbal human sounds as a short connected paragraph. Avoid duplicating dialogue or a second full music arrangement. Follow the official guide's silence convention.
- In `non_diegetic_music`, describe the audience-only score in a short paragraph, or `N/A`. If the soundscape mentions its presence for context, both passages refer to the same track, not extra music.

Reconcile endings in this same response: a logo does not automatically require silence, a cut does not automatically restart music, and a track cannot continue after another section says it stopped. Preserve user-locked endings and source timing. Do not force a fade, swell or final hit onto every clip.

Use perceptual instructions such as “beneath the dialogue” where useful. Do not promise exact LUFS, EQ, compressor settings or millisecond alignment through H3 prose; these are mixer operations, not verified model controls.

For rationale, case contrasts and source limitations, see [references/findings.md](references/findings.md). These are conditional writing observations, not a claim that official videos sound better or a reconstruction of the official internal algorithm.
