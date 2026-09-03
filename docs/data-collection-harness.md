# The data-collector/discriminator pattern — is there a framework under it?

*Survey + verdict, 2026-08-25. Prompted by: "Is this actually its own app somehow? A data
collector discriminator? … if nothing else is there a framework to these frameworks that can
make us more methodical, less wheel-re-inventy?" Everything claimed about a repo below was
read from that repo; paths and symbols are real.*

---

## 1. What each project actually has

### beatboxing (`~/dev/beatboxing`) — freshest and most deliberate

- **KMeter** (`prototype/KMeter/`) is a purpose-built measurement app whose only output is
  one number: how often an intended dodge-sound (inward K) is heard as an attack-sound.
  `prototype/PROTOCOL.md` fixes the decision rule *before* data exists: "<1% ≈ the game
  works · ~8% ≈ the concept is dead". Flow: measure room noise → calibrate 12 reps × 4
  classes plus a `_junk` class → 220-prompt test (K deliberately over-represented, 80/220)
  → confusion matrix + THE metric on a results screen. Results are a Codable
  `StudyResults` (`KMeter/Session.swift`) that also records capture conditions —
  `device`, `micRoute`, `sampleRate`, `ambientRMSdB`, `conditionNote` — and autosaves JSON
  to Documents, pullable via `devicectl … copy from`.
- **Labels are created at capture.** The calibration prompt *is* the label; a `flubbed`
  flag on `TrialRecord` lets the player mark "I made the wrong sound" so their slip isn't
  charged to the classifier; `KNNClassifier.isPlausible(sample:for:)` gates out coughs and
  table bumps before they poison the model. There is no labelling backlog because there is
  no unlabelled data, ever.
- **Active learning is implemented, not aspirational** (`shared/AudioCore/Classifier.swift`,
  commit 2026-08-25 "Active learning: self-audit, targeted top-up rounds, live boundary
  monitor"): `selfAudit()` runs a leave-one-out classification of every calibration anchor;
  `weakestBoxeme()` fingers the class whose anchors mislabel or sit at thin margins;
  after the decoy round the app asks for 4 targeted reps of the weak class (max 2 rounds);
  during play a rolling 60-event window watches per-class rejects and margins and offers a
  one-tap top-up ("Doc: gimme a few more X's"). Measured on simulator: `train()` **39 ms**,
  full leave-one-out self-audit **173 ms** — cheap enough to retrain after every rep.
- The game itself merges calibration into play (commit "Calibration merges into the bag"):
  training mode is the punching bag with Doc's overlay, so calibration stops being a
  separate chore.
- `shared/AudioCore` is pure Swift with "no audio-session dependencies, so it is fully
  testable offline" — the harness runs the *same code* the app runs, by construction.
- `research/06-classification.md` is a full cited literature review grounded in the actual
  code, with a verified-vs-unverified audit at the end.

### teethwatch (`~/dev/teethwatch`) — the most complete pipeline, and the stalled one

- Capture: the spike app records sessions; a session is a basename bundle
  `<yyyymmdd-hhmmss>_<device>.{mov,frames.jsonl,session.json}` dropped in `~/Downloads`,
  re-encoded into `Labels/media/` at constant 30fps.
- Ground truth: a local **Label Studio** instance (`Labels/start.sh`,
  `Labels/setup_project.py`, both idempotent; token read straight out of the sqlite so
  there's never a credential to paste). Four labels with hotkeys, defined in
  `Labels/ETHOGRAM.md`; `holding` (brush parked in mouth, no strokes) is the load-bearing
  one no automated signal can produce.
- **Pre-annotation with independent instruments**: `Labels/pre_annotate.py` drafts spans
  using a COCO person detector + the yolov8n-pose brush/lip model — deliberately different
  instruments from the detector under test, "so neither can be wrong in the same direction
  as the detector being scored". The human job is review-and-fix, not drag-every-span.
  The app's own phase track (`Labels/detector_tracks/*.track.json`) is joined only at
  scoring time so labels can't anchor on the answer being tested.
- Scoring: `Labels/score_labels.py` — headline is **false-pause seconds** (labelled
  `brushing`, app not counting), guardrailed by over-count seconds with `holding`-counted
  and counting-while-`gone` broken out. `--sweep` replays candidate fixes through
  `Labels/replay.py`, "a line-by-line port of `BrushStateMachine.swift`".
- Training: `datasets/train-runs/tbh-pose-n/` is a real yolov8n-pose fine-tune on the
  Roboflow toothbrushing set (80 epochs, ~25 s/epoch on the Mac, ~28 min total per
  `results.csv`).
- **The stall**: `Labels/media/` holds 4 sessions dated 2026-08-08…10, each with a
  `.pre.json` pre-label already generated — and there is no `Labels/export.json`. The
  pipeline has been ready and waiting on a human labelling pass for over two weeks. The
  code is done; the bottleneck is a Mac-bound chore. (§8.)

### sevensegment (`~/dev/sevensegment`) — the deepest offline harness

- `harness/` is "everything that is not the app": pluggable recognizers
  (`harness/recognizers/` — each module exposes `NAME` and
  `run(paths) -> [(prediction | None, ms)]`, where `None` means *refused*, scored
  separately from wrong), `evaluate.py` scoring any recognizer against any manifest-based
  testset, `metrics.py` with product-shaped metrics (`exact`, `cer`, `decimal_error`,
  `refused`, `wrong` — "A wrong answer is much worse than a refusal … the harness … never
  averages them together"), synth data generation, public-dataset fetchers (YUVA,
  Roboflow), fine-tuning, Core ML export, and threshold sweeps.
- `docs/FINDINGS.md` is the methodological crown jewel — it keeps its own overturned
  claims: synthetic-only results didn't generalise (§3), the decisive
  localisation-vs-recognition isolation experiment (§4), a rigged comparison caught and
  redone (§13), checkpoint-selection leakage flagged (§10), **agreement across frames
  beats confidence as a safety signal** (§12: precision 62.5% → 90.9% at the same wrong
  rate), and **in-domain data saturating at ~112 images while 8,400 more bought only
  out-of-domain breadth** (§13).
- Parity is handled the third way: Python is the reference, the Swift port is checked by
  an in-app self-test (`-SevensezSelfTest YES` runs harness frames through the on-device
  pipeline) and a known gap is *written down* (§9: the saturation term isn't in Swift yet).
- Capture: `docs/CAPTURE_PROTOCOL.md` specifies a 150–250-photo shoot (what to shoot, how
  badly to shoot it, why those numbers), and `harness/prep_capture.py` opens a local page
  where the trained detector pre-draws each box so labelling is "typing numbers … ~5
  seconds per image"; `ingest_capture.py` validates and merges into the manifest.
- **Its stall is the same stall**: the shoot hasn't happened (last commit 2026-08-09), and
  §14's blocker is 22 validation images — too few to tune the refusal threshold.

### spinnit (`~/dev/spinnit`) — the loop with no labels at all

- Capture: app Debug tab → Start Recording → spin → Export CSV → AirDrop
  (`python/data/spinnit_recording_*.csv`, 8 recordings from Dec 2025).
- `python/spinnit_detector.py` is a "faithful Python mirror of
  `Spinnit/Services/ActivityDetector.swift`" — and it knows why it exists: calibration
  numbers must be expressed "in the units the *detector* produces, not in units a
  physics-first estimate produces". Drift is machine-checked: `selftest()` compares
  against values the app itself wrote into `tests/snapshots/dynamic/*/manifest.txt`, and
  the header pins "Mirrors ActivityDetector.swift as of commit 0d1389e".
- `python/calibrate.py` turns a recording into ENVELOPE / HITTABILITY / RETUNE — and emits
  *Swift you paste back into `CelestialBodies.swift`*. `SCALING_MODEL.md` is the canonical
  derived-numbers doc.
- No ML and no labels: ground truth is implicit (the person was spinning). It is still the
  same loop — capture in real posture, offline replica of the production discriminator,
  tune, port numbers back.

### izzit (`~/dev/izzit`) — the counter-example

- `tools/ml_training/` (Feb 2026) trained a 42-class, ~26M-param Keras CNN on **Google
  QuickDraw** — public data, not captured data — for Core ML export.
  **It never shipped**: there is no `SketchRecognizer.mlmodel` anywhere in `ios/`, no Swift
  references it, and `TRAINING_STATUS.md` is frozen mid-sentence at "Current Status:
  TRAINING IN PROGRESS" (2026-02-01) — no eval, no confusion matrix, no recorded verdict.
  Production judging is the Google Gemini cloud VLM; the only on-device fallback in the
  tree is `ios/izzit/Services/VisionFrameworkAnalyzer.swift` wrapping Apple's generic
  `VNClassifyImageRequest`, and it isn't the prod path either.
- Two readings, both true: (a) the local model died for a good reason — the cloud VLM was
  simply better at open-ended sketch judging; (b) `ml_training/` is what pre-methodology
  looked like. It has a dataset and an architecture but no deciding metric, no held-out
  eval, no findings doc — the exact things every later harness leads with.
- One observation worth keeping: izzit sits on a naturally *self-labelling* stream — every
  drawing is made against a known prompt — and captures none of it (drawings are ephemeral
  by design). If a local model is ever revisited (e.g. the gemini-3.1 retry falls through),
  that stream is the dataset, already labelled at creation.

### The two adjacent apps

- **fusiontrainer** (`~/dev/fusiontrainer`, Hide and See): no ML pipeline — but it solved
  the ground-truth problem better than any of the above by *construction*: "The app draws
  the picture, so it knows exactly where the hidden shape is. Tapping it is evidence."
  Ground truth is free because the task was designed so the label pre-exists the capture.
- **mindfulpresence** (Curiouser): nothing of this shape. No perception code.

---

## 2. The common loop — and where each project deviates

Stated precisely, the loop every one of these converges on:

1. **Name the deciding number before collecting anything, and make it asymmetric.**
   KMeter: attack-substitution rate with a pre-registered kill threshold. teethwatch:
   false-pause seconds (dominant), over-count as guardrail. sevensez: wrong-rate ("the one
   number to drive to zero"), refusals scored separately. spinnit: longest contiguous run
   inside a target box ("the number that decides whether a body is winnable at all").
   In all four, the two error directions are never averaged, because the product costs
   are never symmetric.
2. **Capture on device, in the real usage posture**, with capture-condition metadata,
   exported by whatever is cheapest (devicectl pull / Downloads bundle / AirDrop CSV /
   camera roll). One session = one timestamped basename + sidecars.
3. **Acquire ground truth** — the stage where the projects diverge most (§8): at capture
   (KMeter prompts), after capture with pre-annotation (teethwatch, sevensez shoot),
   from external annotated datasets (sevensez YUVA/Roboflow, teethwatch Roboflow, izzit
   QuickDraw), or implicitly (spinnit).
4. **Replay the exact production discriminator offline.** Three parity strategies exist in
   the repos: shared pure-Swift core (beatboxing AudioCore), line-by-line mirror with a
   machine-checked drift test (spinnit `selftest()`, teethwatch `replay.py`), and
   Python-as-reference with an in-app self-test plus written-down gaps (sevensez).
   All three exist because everyone got burned the same way: a harness that doesn't run
   the production code produces fiction (sevensez §8 lists four bugs that all presented
   as "the model is bad").
5. **Score with the asymmetric metric; sweep candidates; write results JSON and a findings
   doc that keeps its corrections.** sevensez `results/*.json` + FINDINGS.md, teethwatch
   `score_labels.py --sweep`, spinnit's RETUNE emitting paste-back Swift, KMeter's
   results screen + autosaved JSON.
6. **Aim the next collection at the measured weakness**, not at "more":
   KMeter's `weakestBoxeme()` top-ups; sevensez's capture protocol targeting the unserved
   appliance domain and the 22-image validation gap; teethwatch's next pass existing
   specifically to split `brushing` from `holding`.

Deviations that matter:

| | deciding metric | labels | parity strategy | loop closed? |
|---|---|---|---|---|
| beatboxing | pre-registered kill threshold | **at capture** | shared Swift core | yes — automatically (top-ups) |
| teethwatch | false-pause s | post-hoc, Label Studio | mirror + port | **stalled at labelling** |
| sevensegment | wrong-rate | post-hoc, assisted typing | Swift port + self-test | **stalled at capture shoot** |
| spinnit | contiguous-run s | none (implicit) | mirror + selftest | yes (Dec 2025 round) |
| izzit ml_training | none | public dataset | none | never entered it |

The historical arc is visible: spinnit (Dec 2025) invented the mirror+selftest; teethwatch
(Jun 2026) added ethogram labels, independent-instrument pre-annotation and sweeps;
sevensez (Jul–Aug) added refusal-first metrics, pluggable recognizers, and the
honest-findings culture; KMeter (Aug) added label-at-capture and closed-loop active
learning. **Each project re-derived the previous one's scaffolding in a new shape.** That
is the wheel-reinvention being sensed — and also, honestly, how the method got this good.

---

## 3. What is irreducibly bespoke

- **The capture surface.** Holding the phone like a beatbox mic 5–10 cm from the mouth;
  propping it on a bathroom counter at 0.3–0.8 m; shooting appliance photos "the way a
  blind person would hold a phone"; spinning with the phone in hand. The capture UI *is*
  the product posture. A generic collector app would collect the wrong thing.
- **The feature extraction and model class.** Streaming mel/envelope audio features into
  k-NN; Vision pose/rect observations into a hand-tuned state machine; CenterNet + CTC
  over pixels; smoothed 3-axis IMU into thresholds. Nothing above the file-format level is
  shared, and forcing a common abstraction over them would be all adapter, no substance.
- **The label taxonomy.** Four boxemes + junk; a four-state ethogram whose hardest label
  (`holding`) exists for anti-gameability; digit strings where the decimal point is the
  whole ballgame; no labels at all. Taxonomies encode product judgments, not data shapes.
- **The deciding metric.** Each one is a product thesis in number form. KMeter's
  attack-substitution rate and sevensez's wrong-rate are not instances of a general
  metric; they are the respective products.
- **The discriminator's runtime home.** It must live in each app (latency, privacy,
  offline), so any shared *code* would have to be vendored into every app — the exact
  situation where a shared library rots fastest given one-interactive-session-per-project
  workflow.

---

## 4. The verdict: is this its own app?

**No — and the "probably not, they're always bespoke" instinct is right about the app and
wrong about the framework.** There is no product here: the capture surface, label taxonomy,
and deciding metric — the three things a "data collector discriminator" app would have to
own — are precisely the bespoke parts. Every attempt to genericize those would produce a
worse KMeter, a worse Label-Studio-setup, a worse capture protocol.

But what repeats is not code, it's **method** — and the method is currently stored in five
repos' worth of hard-won scar tissue (sevensez's corrections, spinnit's "why this exists"
docstring, teethwatch's independent-instruments rule, KMeter's pre-registered threshold).
The extractable thing is the playbook plus two file conventions, not a package. §5.

One near-exception worth naming and deliberately deferring: `KNNClassifier` in
`beatboxing/shared/AudioCore/Classifier.swift` is ~350 lines of calibrate/z-score/Fisher/
reject/self-audit machinery whose only bespoke dependency is the `Boxeme` enum. Genericized
over a label type it would be a legitimate "CalibKit" SwiftPM package for any future
per-user-calibrated classifier. **Don't extract it now** — it has exactly one consumer
family (KMeter + the game, already sharing via `shared/`), and a package with one consumer
is a liability. Extract on the second real consumer, not before (rule of three, relaxed to
two because the code is genuinely mature).

---

## 5. What to extract, in what form

The cheapest thing that removes the most repetition, in order:

1. **This playbook** (`~/dev/crew/docs/data-collection-harness.md` — you're reading it).
   The next project of this shape starts by reading §2's loop and §9's list instead
   of re-deriving them. Cost: already paid. Maintenance: additive notes only.
2. **Convention: the session bundle.** One capture = one basename
   `<yyyymmdd-hhmmss>_<device>` + sidecars (`.mov`/`.csv`/`.wav` + `.session.json` with
   capture conditions + `.labels.json` when labels exist). teethwatch and KMeter already
   effectively do this; adopting it verbatim in the next project costs zero and makes
   every past tool a donor.
3. **Convention: the results JSON.** Every harness's headline output includes:
   `harness_version` (git sha), dataset id + split, n, the confusion matrix, the headline
   metric *with its direction stated*, and refusals/rejections broken out from errors —
   never averaged in. sevensez's `results/*.json` and KMeter's `StudyResults` are both
   already ~90% of this. (Optional later: a `crew`-readable one-line status per project —
   but only if wanting to see them side by side ever actually happens.)
4. **House rule: parity or fiction.** The harness must run the production discriminator's
   actual code (shared core), or a mirror with a machine-checked drift test (spinnit
   `selftest()`), or the port must have an in-app self-test (sevensez). A mirror without a
   drift check is banned — it silently becomes a fiction generator. Pin the mirrored
   commit in the mirror's header the way `spinnit_detector.py` does.
5. **Donor pointers instead of a template repo.** When the next project needs a harness,
   copy from the best existing instance rather than maintaining a cookiecutter that will
   rot: `sevensegment/harness/{evaluate,metrics}.py` for offline scoring with
   refusal-aware metrics; `teethwatch/Labels/` for a Label Studio setup with
   pre-annotation; `spinnit/python/spinnit_detector.py` for the mirror pattern;
   `beatboxing/prototype/KMeter` for a prompted-capture measurement app;
   `beatboxing/shared/AudioCore/Classifier.swift` for calibrate/self-audit/top-up.
   A template repo is the "framework that then rots" failure mode; named donors are not.

What NOT to build: a shared Swift/Python library of capture/label/eval code (every
consumer would fight the abstraction), a generic capture app (wrong posture, wrong
prompts), or any MLOps-shaped thing (experiment trackers, DVC, cloud dashboards — wrong
scale for one person with five hobby-sized datasets).

---

## 6. Active learning — what it buys, what it costs

The beatboxing question ("find samples that are confusing, ask for more data when
boundaries aren't working") is already answered in code — `selfAudit()` /
`weakestBoxeme()` / the margin-watching top-up chip, commit 2026-08-25. What the
literature adds is calibration about how much this is worth, and confirmation that the
*shape* chosen is the right one.

**What it buys — honestly less than folklore says.** The founding papers claimed enormous
savings (Lewis & Gale's uncertainty sampling reported up to 500-fold label reductions,
SIGIR 1994 — https://dl.acm.org/doi/10.5555/188490.188495). The modern empirical record is
sober: Lowell, Lipton & Wallace, "Practical Obstacles to Deploying Active Learning"
(EMNLP 2019, https://aclanthology.org/D19-1003/) found AL's gains over random sampling
inconsistent across tasks — and, worse, that an actively-acquired dataset is *coupled to
the model that chose it*: retrain a different model on it and it can underperform random.
Munjal et al. (CVPR 2022, https://arxiv.org/abs/2002.09564) and Mittal et al., "Parting
with Illusions about Deep Active Learning" (https://arxiv.org/abs/1912.05361) both find
marginal-to-no gains over random under well-tuned training. When it does work, the
realistic win is **~1.5–2× label efficiency**; the best directly-relevant result is audio:
cluster-then-label AL for sound event classification saved 50–60% of labelling budget
(Shuyang, Heittola & Virtanen,
https://homepages.tuni.fi/tuomas.virtanen/papers/active-learning-sound.pdf; TASLP 2020
follow-up https://arxiv.org/abs/2002.05033). At tiny budgets, diversity/cluster methods
beat pure uncertainty — an untrained model's "uncertainty" is mostly noise.

**Why the KMeter shape dodges the classic failures.** Pool-based AL (pick which existing
unlabelled item to label) is where the disappointing results live. KMeter does something
different: it asks the *human to perform a fresh example* of a named class. That is
membership query synthesis (Angluin 1988,
https://link.springer.com/article/10.1023/A:1022821128753) with a human generator — which
sidesteps the classic synthesis failure of producing queries no one can label, and also
mostly sidesteps Lowell's coupling caveat, because a rep of "K" collected because the K
boundary looked weak is still a perfectly ordinary labelled K if the features change later
(v2 features are coming; the collected reps survive). The lineage for this loop is
**Wekinator** (Fiebrink, Trueman & Cook, NIME 2009,
https://www.nime.org/proceedings/2009/nime2009_280.pdf) — demonstrate → train → run →
fix-the-worst-class, for musicians, in real time — and its mass-market proof, Teachable
Machine (Carney et al., CHI EA 2020,
https://dl.acm.org/doi/abs/10.1145/3334480.3382839). KMeter independently reinvented this
correctly.

**The self-audit has direct literature support.** Using k-NN disagreement on the labelled
set itself to find bad/confusing anchors is essentially "Deep k-NN for Noisy Labels"
(Bahri, Jiang & Gupta, ICML 2020, https://proceedings.mlr.press/v119/bahri20a.html), and
per-class label-quality diagnosis is Confident Learning (Northcutt, Jiang & Chuang, JAIR
2021, https://arxiv.org/abs/1911.00068 — tooling: cleanlab). Nothing found formalizes the
exact "per-class LOO error → ask for more of class X" recipe, but its two halves are each
established.

**The UX cost is the real cost.** Compute is negligible here (39/173 ms). The interaction
literature's consistent findings: people resent a model that streams questions at them —
in Cakmak & Thomaz's study users of a constantly-querying learner felt they'd lost control
("balance queries with other behavior",
https://sites.cc.gatech.edu/social-machines/papers/cakmak12_hri_active.pdf); and people
are not passive oracles — they want to *test* the model and see fast feedback (Amershi et
al., "Power to the People", AI Magazine 2014,
https://ojs.aaai.org/aimagazine/index.php/aimagazine/article/view/2513; Simard et al.,
"Machine Teaching", https://arxiv.org/abs/1707.06742, argues for optimizing the teacher's
experience, not the learner's). Design rules that follow, all of which the KMeter/game
implementation already obeys: make the request **passive** (a chip, not a modal), **named
and bounded** ("gimme a few more K's" — 4 reps, max 2 rounds), **initiated by one tap**,
and **only when a measured boundary degrades**, never on a schedule. That is the pattern
to copy into any future calibrated app.

**When to skip AL entirely:** when labels are free at capture (prompted calibration) and
classes are few, plain "12 reps of everything, then top up the measured-weakest class" is
already the right amount of active learning. Per-sample uncertainty selection earns its
complexity only when there is a large unlabelled pool and a human-time-expensive labelling
pass — which in this portfolio means teethwatch (§8), not beatboxing.

---

## 7. On-device training cost, with numbers

Direct answers to "how long does training take? could it be done on-device while we're
exploring?":

- **k-NN calibration (KMeter's class of model): effectively free.** Measured in this
  portfolio: `train()` (z-score stats + Fisher weights + LOO reject thresholds over ~60
  vectors, dim 89) **39 ms**; full leave-one-out self-audit **173 ms** — on simulator; the
  A18 is faster. Retraining after every accepted rep is fine. Matthijs Hollemans'
  Core ML training series agrees: k-NN updates are "almost instantaneous — the only thing
  that takes any time is the feature extractor"
  (https://machinethink.net/blog/coreml-training-part3/).
- **Core ML's official on-device path (`MLUpdateTask`) is real but CPU-only.** Updatable
  model types are nearest-neighbor classifiers and neural networks with only
  convolution/fully-connected layers trainable; losses cross-entropy/MSE; optimizers
  SGD/Adam; background updates via BGTaskScheduler (WWDC 2019 session 704,
  https://developer.apple.com/videos/play/wwdc2019/704/; Apple sample:
  https://developer.apple.com/documentation/coreml/personalizing-a-model-with-on-device-updates).
  Hollemans measured that training "never used the GPU or Neural Engine … only the CPU"
  on an iPhone XS, and noted a ~250 MB leak per update task
  (https://machinethink.net/blog/coreml-training-part4/). Fine for heads and k-NN;
  wrong tool for whole small CNNs.
- **Create ML runs in-app on iOS 15+** and can train image / sound / text / tabular
  classifiers on device (WWDC21,
  https://developer.apple.com/videos/play/wwdc2021/10037/). One measured point: an
  on-device `MLImageClassifier` train in ~**30 s on an iPhone 13**
  (https://github.com/moutend/TrainingMLImageClassifier). The tabular family covers the
  decision-tree/boosted-tree niche with a supported API.
- **A 663k-param CNN (sevensez's detector class), estimated:** with the standard trick —
  freeze the backbone, extract features once, train only the head — **seconds** on
  device. Full fine-tune over ~100 images × 10 epochs is ~0.3–1.5 TFLOP: **tens of
  seconds to minutes** on MLUpdateTask's CPU path, **a few seconds** via MPSGraph on the
  GPU (estimates from FLOP counts; MPSGraph training: WWDC20 session 10677,
  https://wwdcnotes.com/documentation/wwdc20-10677-build-customized-ml-models-with-the-metal-performance-shaders-graph/).
- **The portfolio's actual practice matches the industry's:** anything nontrivial trains
  on the Mac and ships as a model — teethwatch's yolov8n-pose fine-tune ran ~25 s/epoch,
  ~28 min total on the Mac (`datasets/train-runs/tbh-pose-n/results.csv`); sevensez's
  detector and recognizer train in `harness/` and export to Core ML. On-device work is
  for *personalization* (per-user calibration), not model development — the explicit
  framing of both Apple's WWDC material and Hollemans' series
  (https://machinethink.net/blog/training-on-device/).

So: **yes, on-device-while-exploring is viable — for exactly the model class KMeter uses**
(k-NN over features, or a frozen-extractor + trainable head). For everything bigger, the
Mac is the training rig and the phone is the capture+inference rig, and no project here
suffers from that split.

---

## 8. The labelling bottleneck — the actually-expensive part

The evidence across projects is unambiguous: **code is never the stall; ground truth is.**
teethwatch has had 4 pre-annotated sessions sitting since 2026-08-10 with no
`export.json`; sevensez has been blocked since ~2026-08-09 on a 30–45 minute photo shoot
and a 22-image validation set. Meanwhile KMeter — the newest project — has *no backlog and
cannot have one*, and that is not luck, it is design.

Ranked by demonstrated effectiveness in these repos:

1. **Label at capture (strongest).** KMeter's prompted calibration makes the label the
   prompt; the `flubbed` button and `isPlausible` gate do label QA at the moment of
   creation; the bag-merge makes calibration indistinguishable from play. spinnit's
   implicit ground truth is the same idea taken to the limit. fusiontrainer's
   tap-the-hidden-shape is the platonic form: design the task so the label pre-exists.
   **Rule: before building any labelling tool, spend an hour trying to redesign capture so
   the label is free.**
2. **Shrink the unit of labelling work below the scheduling threshold.** teethwatch
   already has pre-annotation and still stalled — because the remaining unit of work is
   "sit at the Mac, boot Label Studio, review a whole session". The fix is not better
   pre-labels; it is making the human pass 5 minutes instead of 30: only surface the spans
   where the two independent instruments disagree or the detector's own track flip-flops,
   and auto-accept the rest at draft confidence (they're excluded from scoring anyway when
   unlabelled — flip the default for high-agreement spans). That is active learning
   applied to annotation, and teethwatch is one script-change away from it.
3. **Pre-label with a weak model, human corrects.** Already standard here (teethwatch
   `pre_annotate.py`, sevensez's detector pre-drawing boxes at ~5 s/image). Necessary, not
   sufficient — see 2.
4. **Know when to stop.** sevensez §13: in-domain accuracy saturated at ~112 images;
   8,400 more bought nothing in-domain. The dread of "I need thousands of labels" is
   usually false at this scale; the actual asks in both stalled projects are under an
   hour. Write the target number down (sevensez's protocol does: 150–250 photos, 20+
   validation images) so the chore has a visible end.

---

## 9. Do this next

Ordered, cheapest-highest-value first. The striking thing about this list: the top two
items are sub-hour *human* tasks, not engineering.

1. **Label the 4 waiting teethwatch sessions** (`Labels/media/20260808…20260810`,
   pre-labels already generated). ~30–45 min in Label Studio and the entire
   detector-tuning loop unblocks. Doing it also calibrates how long a session really
   takes, which item 4 needs.
2. **Do the sevensez capture shoot** — `docs/CAPTURE_PROTOCOL.md` is already written:
   150–250 photos, 30–45 min, then ~5 s/image typing in the assisted labeller. This
   unblocks both the domain question and the 22-image validation blocker (§14).
3. **Adopt the two conventions in the next project that captures anything** (§5.2, §5.3:
   session-bundle naming + sidecars; results JSON with confusion, direction-stated
   headline metric, refusals broken out). Zero new code — just don't invent a third
   naming scheme.
4. **Shrink teethwatch's labelling unit** for the *next* batch: surface only spans where
   the two pre-annotation instruments disagree or the detector track flip-flops;
   auto-accept high-agreement spans as draft labels. One script change in
   `Labels/pre_annotate.py` / `setup_project.py`, and labelling a session drops from ~30
   min to ~5. (This is the one place pool-style active learning earns its keep in the
   portfolio — §6.)
5. **Copy the KMeter ask-for-more pattern** (self-audit → named, bounded, one-tap top-up
   chip) into the next per-user-calibrated app, by reading `Classifier.swift`, not by
   extracting a package. Extract "CalibKit" only when a second real consumer exists (§4).
6. **Keep this doc alive as the playbook.** When a harness pays for a new lesson (the way
   sevensez paid for "agreement beats confidence" and spinnit paid for "mirror needs a
   selftest"), add one line here. The framework-of-frameworks is a document, and this is
   it.
7. **Do not build**: the generic collector app, a template repo, a shared harness
   library, or any MLOps tooling (§5, "What NOT to build").
