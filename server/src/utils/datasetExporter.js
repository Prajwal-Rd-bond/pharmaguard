/**
 * Active Learning & Model Fine-Tuning Dataset Exporter for PharmaGuard
 * Converts human corrections and gold-standard feedback into standard ML training formats.
 */

/**
 * Tokenizes text and produces CoNLL-2003 BIO format for Clinical NER models.
 *
 * @param {Array} examples - Array of { rawText, goldExtraction } objects
 * @returns {string} CoNLL BIO formatted text string
 */
export function exportToBioNerFormat(examples) {
  if (!Array.isArray(examples)) return "";

  const lines = [];

  for (const item of examples) {
    const text = item.deidentifiedText || item.rawText || "";
    const gold = item.goldExtraction || {};
    const suspectDrugs = (gold.suspectDrug ? [gold.suspectDrug] : gold.drugs || []).map((d) => d.toLowerCase());
    const symptoms = (gold.symptoms || []).map((s) => s.toLowerCase());

    const words = text.match(/\b[\w'-]+\b|[.,!?;]/g) || [];

    for (const word of words) {
      const lower = word.toLowerCase();
      let tag = "O";

      if (suspectDrugs.some((d) => d.includes(lower))) {
        tag = "B-DRUG";
      } else if (symptoms.some((s) => s.includes(lower))) {
        tag = "B-ADR";
      }

      lines.push(`${word}\t${tag}`);
    }

    lines.push(""); // sentence boundary
  }

  return lines.join("\n");
}

/**
 * Converts FeedbackExamples into Instruction-Tuning JSONL format (Alpaca / OpenAI Chat).
 *
 * @param {Array} examples - Array of FeedbackExample documents
 * @returns {string} JSONL formatted string
 */
export function exportToInstructionJsonl(examples) {
  if (!Array.isArray(examples)) return "";

  const outputLines = [];

  for (const ex of examples) {
    const rawNarrative = ex.deidentifiedText || ex.rawText || "";
    const gold = ex.goldExtraction || {};
    const aiProposed = ex.aiProposedExtraction || {};
    const clinicianCorrection = ex.clinicianDiff || {};

    const prompt = `Extract all suspect medications, adverse drug reactions, dosages, and timelines from the following clinical adverse event narrative:\n\nNarrative:\n${rawNarrative}`;

    const completion = JSON.stringify(
      {
        suspect_drug: gold.suspectDrug || aiProposed.suspectDrug || "Unknown",
        symptoms: gold.symptoms || aiProposed.symptoms || [],
        severity: gold.severity || "moderate",
        action_taken: gold.actionTaken || "Discontinued",
      },
      null,
      2
    );

    const record = {
      messages: [
        {
          role: "system",
          content:
            "You are an expert clinical pharmacovigilance intelligence specialist. Extract suspect medications and adverse reactions with zero hallucination.",
        },
        { role: "user", content: prompt },
        { role: "assistant", content: completion },
      ],
      metadata: {
        exampleId: ex._id ? ex._id.toString() : undefined,
        humanVerified: true,
        diffFields: Object.keys(clinicianCorrection),
      },
    };

    outputLines.push(JSON.stringify(record));
  }

  return outputLines.join("\n");
}

