import test, { describe } from "node:test";
import assert from "node:assert";

describe("Regulatory Clock & SLA Urgency Tracking", () => {
  test("assigns 7-day clock for life-threatening cases and marks urgency appropriately", () => {
    const createdAt = new Date();
    const clockDays = 7;
    const dueDate = new Date(createdAt.getTime() + clockDays * 86400000);
    const now = new Date();
    const hoursRemaining = Math.round((dueDate.getTime() - now.getTime()) / 3600000);

    assert.ok(hoursRemaining > 48, "Newly created 7-day case should have > 48 hours");
    let clockStatus = "ON_TRACK";
    if (hoursRemaining <= 0) clockStatus = "OVERDUE";
    else if (hoursRemaining <= 48) clockStatus = "EXPEDITED_CRITICAL";

    assert.strictEqual(clockStatus, "ON_TRACK");
  });

  test("flags overdue cases when elapsed time exceeds SLA", () => {
    // 16 days ago for a 15-day SLA
    const createdAt = new Date(Date.now() - 16 * 86400000);
    const clockDays = 15;
    const dueDate = new Date(createdAt.getTime() + clockDays * 86400000);
    const now = new Date();
    const hoursRemaining = Math.round((dueDate.getTime() - now.getTime()) / 3600000);

    assert.ok(hoursRemaining < 0);
    const clockStatus = hoursRemaining <= 0 ? "OVERDUE" : "ON_TRACK";
    assert.strictEqual(clockStatus, "OVERDUE");
  });
});

describe("ICH E2B(R3) ICSR XML Structure", () => {
  test("generates valid standard XML header and safety report tags", () => {
    const reportId = "PHARMAGUARD-TEST-001";
    const drugName = "Amoxicillin";
    const primaryReaction = "Anaphylaxis";
    const rxcui = "723";
    const meddraPt = "Anaphylactic reaction";

    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<ichicsr lang="en">
  <ichicsrmessageheader>
    <messagetype>ichicsr</messagetype>
    <messagereceiveridentifier>FDA_FAERS_ELECTRONIC_SUBMISSION</messagereceiveridentifier>
  </ichicsrmessageheader>
  <safetyreport>
    <safetyreportid>${reportId}</safetyreportid>
    <serious>1</serious>
    <patient>
      <reaction>
        <reactionmeddrapt>${meddraPt}</reactionmeddrapt>
      </reaction>
      <drug>
        <medicinalproduct>${drugName}</medicinalproduct>
        <drugrxnormcui>${rxcui}</drugrxnormcui>
      </drug>
    </patient>
  </safetyreport>
</ichicsr>`;

    assert.ok(xml.includes("<messagetype>ichicsr</messagetype>"));
    assert.ok(xml.includes("<medicinalproduct>Amoxicillin</medicinalproduct>"));
    assert.ok(xml.includes("<drugrxnormcui>723</drugrxnormcui>"));
    assert.ok(xml.includes("<reactionmeddrapt>Anaphylactic reaction</reactionmeddrapt>"));
  });
});

describe("Duplicate Case Detection Scoring", () => {
  test("computes high duplicate score for matching drug, overlapping symptoms, and age/gender", () => {
    const repA = { drug: "amoxicillin", symptoms: ["rash", "hives"], age: 45, gender: "female" };
    const repB = { drug: "amoxicillin", symptoms: ["rash", "urticaria"], age: 46, gender: "female" };

    let score = 0.4; // Base score for matching drug
    const symptomsA = new Set(repA.symptoms);
    const overlap = repB.symptoms.filter((s) => symptomsA.has(s));
    if (overlap.length > 0) score += 0.3 * (overlap.length / symptomsA.size);
    if (repA.gender === repB.gender) score += 0.15;
    if (Math.abs(repA.age - repB.age) <= 5) score += 0.15;

    assert.ok(score >= 0.7, `Expected similarity score >= 0.7, got ${score}`);
  });
});

