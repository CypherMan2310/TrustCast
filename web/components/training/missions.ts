/**
 * Forecaster Training: missions, copy and completion rules.
 *
 * Each step names the element to spotlight (a `data-tour` id), the screen it lives on, and, for
 * action steps, which app event completes it. Pages report events through `useTrainingReporter()`;
 * nothing here reaches into page state. Steps without `onEvent` are read-and-continue.
 */

export type TrainingEvent =
  | { type: "lead-changed"; lead: number }
  | { type: "layer-changed"; layer: string }
  | { type: "district-opened"; id: string; name: string }
  | { type: "day-selected"; lead: number }
  | { type: "skill-lead"; lead: number }
  | { type: "replay-selected"; id: string; title: string }
  | { type: "replay-lead"; lead: number }
  | { type: "bulletin-lang"; lang: string }
  | { type: "override-saved" };

export type StepVerdict = "done" | { hint: string } | undefined;

export interface Step {
  id: string;
  title: string;
  body: string;
  /** `data-tour` id to spotlight; omit for a centred step. */
  target?: string;
  /** Screen the step runs on (default: the mission's route). */
  on?: (path: string) => boolean;
  onEvent?: (e: TrainingEvent) => StepVerdict;
}

export interface Mission {
  id: string;
  title: string;
  badge: string;
  blurb: string;
  /** Where "Take me there" goes. */
  route: string;
  steps: Step[];
}

const home = (p: string) => p === "/";
const district = (p: string) => p.startsWith("/district/");

export const MISSIONS: Mission[] = [
  {
    id: "read-the-map",
    title: "Read the Map",
    badge: "Map Reader",
    blurb: "Lead days, layers and the colour scale of the blended forecast.",
    route: "/",
    steps: [
      {
        id: "lead",
        title: "Look three days ahead",
        body: "Each tab is one IMD day (08:30 to 08:30 IST). Select Day 3 to see the forecast for the day after tomorrow.",
        target: "lead-tabs",
        onEvent: (e) => (e.type === "lead-changed" ? (e.lead === 3 ? "done" : { hint: `That is Day ${e.lead}. Pick Day 3.` }) : undefined),
      },
      {
        id: "layer",
        title: "Where do the models disagree?",
        body: "The blend is one number, but the models behind it can disagree a lot. Switch the layer to “Model disagreement”.",
        target: "layer-select",
        onEvent: (e) =>
          e.type === "layer-changed" ? (e.layer === "disagreement" ? "done" : { hint: "Choose “Model disagreement” in the Blend group." }) : undefined,
      },
      {
        id: "legend",
        title: "Read the colour scale",
        body: "Rain classes follow IMD categories: 64.5 mm is heavy and 115.6 mm very heavy. Wide disagreement plus a high expected error is what raises the “forecaster review” flag.",
        target: "legend",
      },
      {
        id: "stats",
        title: "The region at a glance",
        body: "These tiles summarise the layer you are looking at: maximum, average, area above the heavy-rain or heatwave threshold, and how many districts have alerts.",
        target: "stats",
      },
    ],
  },
  {
    id: "open-a-district",
    title: "Open a District",
    badge: "District Analyst",
    blurb: "From the map to one district: five days, uncertainty and why the blend trusts whom.",
    route: "/",
    steps: [
      {
        id: "click",
        title: "Click any district",
        body: "District outlines are clickable. Open any district on the map to see its forecast card.",
        target: "forecast-map",
        on: home,
        onEvent: (e) => (e.type === "district-opened" ? "done" : undefined),
      },
      {
        id: "day",
        title: "Compare the days",
        body: "Each card is one lead day with its value and calibrated 90 % range. Select Day 4.",
        target: "day-strip",
        on: district,
        onEvent: (e) => (e.type === "day-selected" ? (e.lead === 4 ? "done" : { hint: `That is Day ${e.lead}. Select Day 4.` }) : undefined),
      },
      {
        id: "why",
        title: "Why this number?",
        body: "Every forecast explains itself: the models it leans on (with weights), the main drivers of that weighting, and the weather regime. Nothing here is hidden.",
        target: "why",
        on: district,
      },
    ],
  },
  {
    id: "who-to-trust",
    title: "Who to Trust",
    badge: "Skill Scout",
    blurb: "Which model has been most accurate, place by place and lead by lead.",
    route: "/skill",
    steps: [
      {
        id: "map",
        title: "The best model changes with place",
        body: "Each cell shows the model with the lowest recent error, using only verification that finished before the run. Hover a cell to see which one.",
        target: "skill-map",
      },
      {
        id: "lead",
        title: "And with lead time",
        body: "Switch to Day 5 and watch how the picture changes further ahead.",
        target: "skill-lead",
        onEvent: (e) => (e.type === "skill-lead" ? (e.lead === 5 ? "done" : { hint: `That is Day ${e.lead}. Pick Day 5.` }) : undefined),
      },
      {
        id: "forest",
        title: "Ranked, with honest intervals",
        body: "Lower error is better. The bars are 95 % intervals from a paired block bootstrap: where they overlap, the difference is not proven.",
        target: "forest",
      },
    ],
  },
  {
    id: "replay-a-disaster",
    title: "Replay a Disaster",
    badge: "Storm Historian",
    blurb: "Go back to a real event and see what every model said beforehand.",
    route: "/replay",
    steps: [
      {
        id: "pick",
        title: "Choose the Wayanad landslides",
        body: "On 30 July 2024 Wayanad received over 120 mm in a day. Select that event.",
        target: "event-cards",
        onEvent: (e) =>
          e.type === "replay-selected" ? (e.id.startsWith("wayanad") ? "done" : { hint: `That is “${e.title}”. Pick the Wayanad landslides.` }) : undefined,
      },
      {
        id: "lead",
        title: "Three days before",
        body: "Switch the scorecard to 3 days ahead: what did each model say on 27 July?",
        target: "replay-lead",
        onEvent: (e) => (e.type === "replay-lead" ? (e.lead === 3 ? "done" : { hint: `That is ${e.lead} day${e.lead > 1 ? "s" : ""} ahead. Pick 3d.` }) : undefined),
      },
      {
        id: "read",
        title: "Be honest about misses",
        body: "The black line is what IMD observed. Here every forecast fell short, and the AI model came closest. Replays show where the blend is not better too.",
        target: "scorecard",
      },
    ],
  },
  {
    id: "duty-forecaster",
    title: "Duty Forecaster",
    badge: "Duty Forecaster",
    blurb: "Read the bulletin in Hindi and record a forecaster override (sandbox, nothing is saved).",
    route: "/district/kerala-wayanad?variable=precip",
    steps: [
      {
        id: "hindi",
        title: "Bulletin in Hindi",
        body: "Bulletins are generated from the numbers on this page and every number is checked. Switch the bulletin to हिन्दी.",
        target: "bulletin",
        on: district,
        onEvent: (e) => (e.type === "bulletin-lang" ? (e.lang === "hi" ? "done" : undefined) : undefined),
      },
      {
        id: "override",
        title: "Record an override",
        body: "You know something the models missed? Tick a model to distrust, give a reason and your name, then Save. In training this is a simulation: nothing is stored.",
        target: "override",
        on: district,
        onEvent: (e) => (e.type === "override-saved" ? "done" : undefined),
      },
    ],
  },
  {
    id: "trust-but-verify",
    title: "Trust but Verify",
    badge: "Verifier",
    blurb: "How every layer had to earn its place on held-out data.",
    route: "/verification",
    steps: [
      {
        id: "gates",
        title: "Every layer earns its place",
        body: "A layer ships only if it is significantly better at 3 or more of 5 lead days and worse at none. Half of them did not pass, and they are switched off. That is the point.",
        target: "gate-matrix",
      },
      {
        id: "sources",
        title: "The frozen source set",
        body: "These models had a complete development history and are the only ones the blend uses. The 2026 test is frozen and run once.",
        target: "frozen-sources",
      },
    ],
  },
];

export const XP_PER_MISSION = 100;

export const RECAP =
  "You have used the whole TRUSTCAST loop: a blended forecast on the IMD grid, the uncertainty and disagreement behind it, district explanations, skill that changes with place and lead time, honest replays of real disasters, forecaster overrides that feed back into the weights, and the verification gates that decide which layers ship. Decision-support tool. Not an official warning.";
