# Interview Guide

Inspect the user's request and available file metadata first. Ask only for
decisions that cannot be safely inferred, one question at a time. Skip every
question whose answer is already known. Do not force the user through a fixed
wizard.

## Conditional question order

Ask for missing decisions in this exact order:

1. **Source:** Obtain a local CSV, JSON, or XLSX path. For pasted tabular data,
   get approval to write it to a temporary local UTF-8 CSV, write only that
   approved temporary file, and inspect the CSV as the source.
2. **View:** Choose wins, losses, all-stage progression, or positive
   progression.
3. **Range:** Confirm the chronological month columns to include.
4. **Mapping:** Confirm Area, Sub-area, Opportunity Name, TCV, Probability, and
   month columns only when aliases are ambiguous.
5. **Semantics:** Confirm terminal aliases, ordered stage paths, and special
   positive transitions needed by this dataset.
6. **Filters:** Accept optional Area, Sub-area, TCV, probability, or opportunity
   filters.
7. **Output:** Default to 1920×1080 SVG, HTML, and PNG pages. Ask only when the
   user needs a different size, format, or destination.
8. **Confidentiality:** If the data appears sensitive, state that parsing and
   rendering remain local and confirm the output destination before writing.

Inspection can reveal another missing decision. Ask the next unresolved item
in this order, then rerun inspection as needed. When multiple XLSX sheets,
ambiguous columns or months, or unknown transitions affect inclusion, resolve
only one ambiguity per question.

## Question patterns

- Source: “Which local CSV, JSON, or XLSX file should I inspect?”
- View: “Should this show wins, losses, all-stage progression, or positive
  progression?”
- Range: “I found monthly stages from March through May. Use all three months?”
- Mapping: “Should `Deal Value` map to TCV?”
- Semantics: “Should Deferred be a negative terminal or a non-terminal stage?”
- Filters: “Should I limit this to any Area, Sub-area, TCV, probability, or
  opportunity?”
- Output: “Use 1920×1080 SVG, HTML, and PNG pages in the default timestamped
  output directory?”
- Confidentiality: “Rendering stays local. May I write the artifacts to this
  destination?”

## Playback and confirmation

Before creating artifacts, play back a concise execution summary containing
the source and selected rows, view, range, stage rules, filters, output formats,
dimensions, and destination. Ask the user to confirm. Do not normalize into a
run directory or render until confirmation. If the user corrects an item,
return to that decision, update the playback, and ask for confirmation again.

## Positive triggers

- “Create an Ericsson opportunity progression infographic from this spreadsheet.”
- “Show me only the opportunities we won this quarter.”
- “Make a losses view from this pipeline data.”
- “Visualize positive opportunity movement from March through May.”
- “Turn this CSV into a 16:9 Ericsson stage-progression visual.”
- “Create a slide-ready view of our TCV, probability, and monthly stages.”
- “Which deals progressed positively, and can you visualize them?”
- “Make the Loop24 opportunity image from this data.”

## Negative examples

Do not activate this skill for these requests. Route generic image requests to
the ordinary image capability, and leave unrelated data requests with their
appropriate tool or skill.

- “Generate an image of a cellular tower at sunset.”
- “Make this headshot look more professional.”
- “What opportunities are assigned to me in Jira?”
- “Create a pie chart from these survey results.”
