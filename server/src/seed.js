import "dotenv/config";
import mongoose from "mongoose";
import bcrypt from "bcryptjs";
import User from "./models/User.js";
import Report from "./models/Report.js";
import Extraction from "./models/Extraction.js";
import Classification from "./models/Classification.js";
import AuditLog from "./models/AuditLog.js";
import crypto from "crypto";

const MONGO_URI = process.env.MONGO_URI || "mongodb://localhost:27017/pharmaguard";

export async function seedDatabase() {
  if (process.env.NODE_ENV === "production") {
    console.log("[seed] NODE_ENV=production detected; skipping database seed.");
    return;
  }

  console.log(`[seed] Connecting to MongoDB: ${MONGO_URI}`);
  await mongoose.connect(MONGO_URI);

  const existingUserCount = await User.countDocuments();
  if (existingUserCount > 0) {
    console.log(`[seed] Existing database has ${existingUserCount} users; preserving all existing accounts.`);
    return;
  }

  console.log("[seed] Initializing demo users for local development environment...");

  // 1. Seed default users
  const defaultUsers = [
    {
      name: "System Administrator",
      email: "admin@pharmaguard.org",
      password: process.env.DEV_ADMIN_PASSWORD || "Admin@12345",
      role: "admin",
    },
    {
      name: "Dr. Sarah Lin (Pharmacovigilance Lead)",
      email: "pharmacist@pharmaguard.org",
      password: process.env.DEV_PHARMACIST_PASSWORD || "Pharma@12345",
      role: "pharmacist",
    },
    {
      name: "Dr. Marcus Vance (Cardiologist)",
      email: "doctor@pharmaguard.org",
      password: process.env.DEV_DOCTOR_PASSWORD || "Doctor@12345",
      role: "doctor",
    },
    {
      name: "Elena Rostova (Safety Epidemiologist)",
      email: "researcher@pharmaguard.org",
      password: process.env.DEV_RESEARCHER_PASSWORD || "Research@12345",
      role: "researcher",
    },
  ];

  const userMap = {};

  for (const u of defaultUsers) {
    const passwordHash = await bcrypt.hash(u.password, 10);
    const created = await User.create({
      name: u.name,
      email: u.email,
      passwordHash,
      role: u.role,
      active: true,
      mfaEnabled: false,
    });
    console.log(`[seed] Created demo user: ${u.email} (${u.role})`);
    userMap[u.role] = created;
  }

  // 2. Check if sample reports exist
  const reportCount = await Report.countDocuments();
  if (reportCount === 0) {
    console.log("[seed] Seeding sample ADR reports with ICH E2A seriousness criteria...");

    const doctor = userMap["doctor"];
    const pharmacist = userMap["pharmacist"];

    // Case 1: Life-threatening Anaphylaxis (Atorvastatin + Lisinopril) - 7-day expedited clock
    const runId1 = "seed-run-" + crypto.randomUUID().slice(0, 8);
    const deadline1 = new Date();
    deadline1.setDate(deadline1.getDate() + 7);

    const report1 = await Report.create({
      submittedBy: doctor._id,
      source: "pasted_text",
      rawText: "Patient presented with acute angioedema and anaphylaxis 45 minutes following administration of Lisinopril 20mg. Required emergent IM epinephrine, high-flow oxygen, and IV methylprednisolone in ICU.",
      deidentifiedText: "[PATIENT] presented with acute angioedema and anaphylaxis 45 minutes following administration of Lisinopril 20mg. Required emergent IM epinephrine, high-flow oxygen, and IV methylprednisolone in ICU.",
      status: "pending_review",
      aiSummary: "Emergent life-threatening angioedema following Lisinopril administration. Immediate hypersensitivity reaction requiring intensive care stabilization.",
      summary: "Emergent life-threatening angioedema following Lisinopril administration. Immediate hypersensitivity reaction requiring intensive care stabilization.",
      patient: {
        age: 58,
        sex: "female",
        weightKg: 68,
      },
      regulatoryClock: {
        days: 7,
        deadline: deadline1,
        isExpedited: true,
      },
      causality: {
        naranjoScore: 8,
        naranjoCategory: "Probable",
        whoUmcCategory: "Probable",
        pharmacistConfirmed: false,
      },
      ichSeriousness: ["life_threatening", "hospitalization"],
      ichE2ACriteria: ["life_threatening", "hospitalization"],
      pipelineRunId: runId1,
    });

    await Extraction.create({
      report: report1._id,
      pipelineRunId: runId1,
      drugName: "Lisinopril",
      genericName: "lisinopril",
      dosage: "20mg",
      frequency: "once daily",
      route: "oral",
      symptoms: ["angioedema", "anaphylaxis", "dyspnea", "urticaria"],
      onsetTimeline: "45 minutes after ingestion",
      age: 58,
      gender: "female",
      comorbidities: ["hypertension"],
      concomitantDrugs: ["atorvastatin"],
      incomplete: false,
      rxNormId: "29046",
      meddraCodes: [
        { term: "Angioedema", pt: "Angioedema", soc: "Immune system disorders", code: "10002424" },
        { term: "Anaphylactic reaction", pt: "Anaphylactic reaction", soc: "Immune system disorders", code: "10002198" },
      ],
      modelVersion: "ollama:llama3.2:3b",
      promptVersion: "v2.1",
    });

    await Classification.create({
      report: report1._id,
      pipelineRunId: runId1,
      severity: "life_threatening",
      isSerious: true,
      seriousnessCriteria: ["life_threatening", "hospitalization"],
      confidence: 0.94,
      modelName: "rule_and_classifier_ensemble",
      modelVersion: "1.0",
      rationale: "Immediate airway compromise requiring epinephrine and ICU hospitalization qualifies under ICH E2A expedited 7-day clock.",
      priorityReview: true,
    });

    // Case 2: Serious Stevens-Johnson Syndrome (Carbamazepine) - 15-day regulatory clock
    const runId2 = "seed-run-" + crypto.randomUUID().slice(0, 8);
    const deadline2 = new Date();
    deadline2.setDate(deadline2.getDate() + 15);

    const report2 = await Report.create({
      submittedBy: doctor._id,
      source: "manual_form",
      rawText: "A 42-year-old male developed extensive bullous epidermal detachment and mucosal erosions covering 8% BSA two weeks after initiating Carbamazepine 200mg BID for trigeminal neuralgia. Admitted to burn unit; skin biopsy confirmed Stevens-Johnson syndrome.",
      deidentifiedText: "A [AGE]-year-old male developed extensive bullous epidermal detachment and mucosal erosions covering 8% BSA two weeks after initiating Carbamazepine 200mg BID for trigeminal neuralgia. Admitted to burn unit; skin biopsy confirmed Stevens-Johnson syndrome.",
      status: "pending_review",
      aiSummary: "Severe cutaneous adverse reaction (Stevens-Johnson syndrome) following Carbamazepine therapy requiring burn unit admission.",
      summary: "Severe cutaneous adverse reaction (Stevens-Johnson syndrome) following Carbamazepine therapy requiring burn unit admission.",
      patient: {
        age: 42,
        sex: "male",
        weightKg: 74,
      },
      regulatoryClock: {
        days: 15,
        deadline: deadline2,
        isExpedited: false,
      },
      causality: {
        naranjoScore: 9,
        naranjoCategory: "Definite",
        whoUmcCategory: "Certain",
        pharmacistConfirmed: false,
      },
      ichSeriousness: ["hospitalization", "disability"],
      ichE2ACriteria: ["hospitalization", "disability"],
      pipelineRunId: runId2,
    });

    await Extraction.create({
      report: report2._id,
      pipelineRunId: runId2,
      drugName: "Carbamazepine",
      genericName: "carbamazepine",
      dosage: "200mg",
      frequency: "twice daily",
      route: "oral",
      symptoms: ["bullous rash", "epidermal detachment", "mucosal ulceration", "Stevens-Johnson syndrome"],
      onsetTimeline: "14 days post initiation",
      age: 42,
      gender: "male",
      comorbidities: ["trigeminal neuralgia"],
      concomitantDrugs: [],
      incomplete: false,
      rxNormId: "2002",
      meddraCodes: [
        { term: "Stevens-Johnson syndrome", pt: "Stevens-Johnson syndrome", soc: "Skin and subcutaneous tissue disorders", code: "10042033" },
        { term: "Epidermal necrosis", pt: "Toxic epidermal necrolysis", soc: "Skin and subcutaneous tissue disorders", code: "10044223" },
      ],
      modelVersion: "ollama:llama3.2:3b",
      promptVersion: "v2.1",
    });

    await Classification.create({
      report: report2._id,
      pipelineRunId: runId2,
      severity: "serious",
      isSerious: true,
      seriousnessCriteria: ["hospitalization", "disability"],
      confidence: 0.92,
      modelName: "rule_and_classifier_ensemble",
      modelVersion: "1.0",
      rationale: "Severe cutaneous adverse reaction (SCAR/SJS) necessitating burn unit admission and resulting in temporary disability.",
      priorityReview: true,
    });
    // Create Initial Hash-Chained Audit Logs
    await AuditLog.create({
      actor: doctor._id,
      actorType: "user",
      action: "report.created",
      report: report1._id,
      details: { drug: "Lisinopril", severity: "life_threatening", clock: 7 },
    });

    await AuditLog.create({
      actor: doctor._id,
      actorType: "user",
      action: "report.created",
      report: report2._id,
      details: { drug: "Carbamazepine", severity: "serious", clock: 15 },
    });

    console.log("[seed] Successfully seeded initial reports and cryptographic audit chain.");
  } else {
    console.log(`[seed] Existing database has ${reportCount} reports; skipping sample reports.`);
  }

  console.log("\n=======================================================");
  console.log("   PharmaGuard Demo User Accounts Ready (Dev Seed):");
  console.log("   ----------------------------------------------------");
  console.log("   Admin:       admin@pharmaguard.org");
  console.log("   Pharmacist:  pharmacist@pharmaguard.org");
  console.log("   Doctor:      doctor@pharmaguard.org");
  console.log("   Researcher:  researcher@pharmaguard.org");
  console.log("=======================================================\n");
}

if (process.argv[1] && process.argv[1].endsWith("seed.js")) {
  seedDatabase()
    .then(() => process.exit(0))
    .catch((err) => {
      console.error("[seed] Error seeding database:", err);
      process.exit(1);
    });
}
