# Tongxing: helping Chinese-speaking attendees follow English sermons

[中文](README.zh.md) · [Listen and read](https://ai-for-god-sermon-audio.web.app/) · [MIT License](LICENSE)

Tongxing is a personal open-source project that helps Chinese-speaking attendees understand English sermons, then read, revisit and discuss them before or after a service. Prepared production has also expanded to Korean and Spanish; the languages available for each week depend on what has been reviewed and published.

There are usually about 10–12 hours between receiving the source video and the next service. That evening must cover text, audio, listening review and delivery, with room to correct problems. Our [weekly production retrospective (Chinese)](docs/blog/sermon-production-workflow-lessons.zh.md) describes the challenges and the improvements underway.

This is an independent personal project, with no affiliation, endorsement or operational relationship with Mariners Church. Use public or authorized media and preserve the source and review status of generated translations, speech and explanations.

## Three ways to use the project

### 1. Listen to a prepared sermon

For a confirmed source video, prepare translated text, speech, captions and an outline. Listeners can choose a weekly edition, follow its captions, or download the audio to revisit it after a service.

Prepared speech follows **the same recording**. Speaker-reference audio requires authorization, and the resulting speech remains generated content. Content review and actual playback quality are checked separately.

[Open the listening app](https://ai-for-god-sermon-audio.web.app/) · [Tongxing iOS client guide (Chinese)](apps/tongxing-ios/README.zh.md)

### 2. Read bilingual materials

Prepare an English–Chinese reading edition and a Chinese sermon companion from a public or authorized video. These support preparation, reflection and group discussion, or provide a reading option when listening is inconvenient.

Each run must confirm the source, sermon boundaries and text before reviewing the PDFs. Historical examples and production guidance are in the [dual-PDF workflow](docs/stable-post-live-reading-pdf-workflow.md).

### 3. Follow the current live delivery

When a speaker delivers the message live, captions use **what is being said in that session**. Chinese text appears on the operator and viewer pages to help attendees follow the current speech.

This path still needs validation of actual audio input, translation quality, phone display and venue conditions. See the [Sunday caption guide (Chinese)](docs/sunday-live-operations-whitepaper.zh.md); [preparing a session](docs/sunday-live-agent-runbook.zh.md) first opens the operator page in standby.

## The same message is not necessarily the same recording

Saturday and Sunday may share a theme while differing in wording, order, examples and spontaneous additions. Prepared audio and caption timing apply to the confirmed recording and cannot simply be reused for another live delivery.

Preparation materials can provide background, terminology and Scripture references, but cannot replace the current session's audio. This distinction determines when to use prepared listening and when to use live captions.

## What listeners receive

| Deliverable | Purpose |
|---|---|
| Weekly listening page | Choose published content and languages; listen with captions and an outline |
| Generated speech and timed captions | Follow the confirmed source video or revisit it afterward |
| Bilingual reading PDF and Chinese companion | Prepare, reflect and discuss |
| Live-session viewer page | Follow the current delivery, subject to the relevant venue validation |
| Weekly sharing poster | A QR code for the exact weekly page; sending and sharing follow the user's instructions |

These are outputs of the different paths; every feature is not automatically available every week. Source videos, complete audio and production materials stay outside Git.

## How we decide content is ready

We check whether the source is complete, the translation preserves its meaning, the speech sounds natural and the captions follow the delivery. Program checks and model review are accompanied by the relevant human text review and listening checks.

A published page and playable files establish the corresponding delivery checks. Actual phone playback and venue performance require separate validation. Historical records also retain cases where preview acceptance was followed by field problems, so one passing check is not treated as acceptance in every setting.

## Learn more and contribute

<a id="architecture-and-design-map"></a>
<a id="four-layer-production-architecture-shared-english-source-to-multilingual-playback"></a>

This homepage introduces the purpose and user experience. Implementation details, diagrams, model experiments and dated records live in separate documents.

- [Project technical overview](docs/project-technical-overview.md): migrated implementation notes, diagrams and experiment records, including the [four-layer diagram](docs/project-technical-overview.md#four-layer-production-architecture-shared-english-source-to-multilingual-playback).
- [Workflow overview (Chinese)](docs/workflows/README.zh.md): scope and deliverables for the three paths.
- [Four-layer production contract (Chinese)](docs/multilingual-production-interfaces.zh.md): dependencies and review requirements from source to text, audio and page.
- [Local experiment logging (Chinese)](experiments/local_experiment_log/README.zh.md): hash-bound accounting measurements and the [three-minute preload/batch protocol](docs/local-preload-batch-experiment.zh.md).
- [App design](docs/app-system-design.zh.md) · [Backend design](docs/backend-workflow-system-design.zh-en.md) · [Experiment directions](docs/experiment-directions.zh.md).
- [Full documentation index](docs/README.md): operations, development and historical evidence.

Contributions through issue reports, user feedback, translation review and code improvements are welcome. Include the week, language and use setting when reporting a problem, so content, playback and venue issues can be understood separately.
