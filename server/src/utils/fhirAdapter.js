/**
 * HL7 FHIR R4 Interoperability Adapter for PharmaGuard
 * Conforms to HL7 FHIR R4 AdverseEvent and Bundle Resource Specifications.
 */

/**
 * Parses an incoming FHIR R4 AdverseEvent or Bundle resource into a PharmaGuard intake object.
 *
 * @param {Object} fhirData - HL7 FHIR R4 JSON resource (AdverseEvent or Bundle)
 * @returns {Object} Normalized intake data for PharmaGuard Report creation
 */
export function parseFhirAdverseEvent(fhirData) {
  if (!fhirData || typeof fhirData !== "object") {
    throw new Error("Invalid FHIR payload: Resource must be a non-null object.");
  }

  let adverseEvent = null;
  let patientResource = null;
  let medicationResources = [];

  if (fhirData.resourceType === "Bundle") {
    const entries = fhirData.entry || [];
    for (const entry of entries) {
      const res = entry.resource;
      if (!res) continue;
      if (res.resourceType === "AdverseEvent") adverseEvent = res;
      else if (res.resourceType === "Patient") patientResource = res;
      else if (res.resourceType === "MedicationAdministration" || res.resourceType === "MedicationStatement") {
        medicationResources.push(res);
      }
    }
    if (!adverseEvent) {
      throw new Error("Invalid FHIR Bundle: Bundle must contain an AdverseEvent resource.");
    }
  } else if (fhirData.resourceType === "AdverseEvent") {
    adverseEvent = fhirData;
  } else {
    throw new Error(
      `Unsupported FHIR resourceType '${fhirData.resourceType}'. Expected 'AdverseEvent' or 'Bundle'.`
    );
  }

  // 1. Extract Suspect Drug
  let suspectDrug = "Unknown Medication";
  if (Array.isArray(adverseEvent.suspectEntity) && adverseEvent.suspectEntity.length > 0) {
    const primaryEntity = adverseEvent.suspectEntity[0];
    const instance = primaryEntity.instance;
    if (instance) {
      suspectDrug = instance.display || instance.concept?.text || instance.reference || suspectDrug;
    }
    // Also check substance if instance is absent
    if (primaryEntity.substance?.concept?.text) {
      suspectDrug = primaryEntity.substance.concept.text;
    }
  } else if (medicationResources.length > 0) {
    const med = medicationResources[0];
    suspectDrug =
      med.medicationCodeableConcept?.text ||
      med.medicationCodeableConcept?.coding?.[0]?.display ||
      suspectDrug;
  }

  // 2. Extract Adverse Reaction / Symptoms
  const symptoms = [];
  if (adverseEvent.event) {
    if (adverseEvent.event.text) {
      symptoms.push(adverseEvent.event.text);
    }
    if (Array.isArray(adverseEvent.event.coding)) {
      for (const coding of adverseEvent.event.coding) {
        if (coding.display && !symptoms.includes(coding.display)) {
          symptoms.push(coding.display);
        }
      }
    }
  }

  // 3. Extract Seriousness Criteria
  const seriousnessCriteria = [];
  let isSerious = false;
  if (adverseEvent.seriousness?.coding) {
    for (const coding of adverseEvent.seriousness.coding) {
      const code = (coding.code || "").toLowerCase();
      const display = (coding.display || "").toLowerCase();
      if (code.includes("death") || display.includes("death") || display.includes("fatal")) {
        seriousnessCriteria.push("death");
        isSerious = true;
      } else if (code.includes("life") || display.includes("life-threatening")) {
        seriousnessCriteria.push("life_threatening");
        isSerious = true;
      } else if (code.includes("hosp") || display.includes("hospital")) {
        seriousnessCriteria.push("hospitalization");
        isSerious = true;
      } else if (code.includes("disab") || display.includes("disability")) {
        seriousnessCriteria.push("disability");
        isSerious = true;
      } else if (code.includes("cong") || display.includes("congenital")) {
        seriousnessCriteria.push("congenital_anomaly");
        isSerious = true;
      } else if (code.includes("ser") || display.includes("serious")) {
        seriousnessCriteria.push("medically_significant");
        isSerious = true;
      }
    }
  }

  // Fallback seriousness check from outcome
  if (adverseEvent.outcome?.coding) {
    for (const c of adverseEvent.outcome.coding) {
      const code = (c.code || "").toLowerCase();
      if (code.includes("fatal") || code.includes("death")) {
        if (!seriousnessCriteria.includes("death")) seriousnessCriteria.push("death");
        isSerious = true;
      }
    }
  }

  // 4. Extract Patient Information
  const subjectId =
    adverseEvent.subject?.reference ||
    adverseEvent.subject?.identifier?.value ||
    patientResource?.id ||
    "ANONYMOUS_PATIENT";

  let patientAge = null;
  let patientGender = patientResource?.gender || null;

  // 5. Construct Synthesized Raw Narrative Text
  const dateStr = adverseEvent.date ? new Date(adverseEvent.date).toISOString().split("T")[0] : "Recent";
  const reactionStr = symptoms.length > 0 ? symptoms.join(", ") : "Unspecified adverse reaction";
  const narrative = `FHIR Intake Report for Patient ${subjectId} (Gender: ${patientGender || "Unspecified"}, Recorded: ${dateStr}). Suspect Medication: ${suspectDrug}. Reported Adverse Reaction: ${reactionStr}. Seriousness Assessment: ${isSerious ? "Serious (" + seriousnessCriteria.join(", ") + ")" : "Non-serious"}. Clinical status: ${adverseEvent.actuality || "actual"}.`;

  return {
    source: "fhir_r4",
    fhirResourceId: adverseEvent.id || `ae-${Date.now()}`,
    subjectIdentifier: subjectId,
    suspectDrug,
    symptoms,
    isSerious,
    seriousnessCriteria,
    patientGender,
    patientAge,
    recordedDate: adverseEvent.date ? new Date(adverseEvent.date) : new Date(),
    rawText: narrative,
    rawResource: fhirData,
  };
}

/**
 * Serializes a PharmaGuard Report and associated AI extraction into an HL7 FHIR R4 AdverseEvent resource.
 *
 * @param {Object} report - Mongoose Report document
 * @param {Object} extraction - Mongoose Extraction document (optional)
 * @param {Object} classification - Mongoose Classification document (optional)
 * @returns {Object} Compliant HL7 FHIR R4 AdverseEvent JSON resource
 */
export function exportReportToFhir(report, extraction = null, classification = null) {
  if (!report) throw new Error("Report object is required for FHIR export");

  const suspectDrugName = extraction?.drugName || "Unknown Suspect Drug";
  const symptoms = extraction?.symptoms || [];
  const primaryReaction = symptoms[0] || "Adverse Drug Reaction";
  const rxNorm = report.terminology?.drugRxNorm;
  const meddraEvent = report.terminology?.meddraAdverseEvents?.[0];

  const seriousnessCoding = [];
  if (report.ichE2ACriteria && report.ichE2ACriteria.length > 0) {
    for (const c of report.ichE2ACriteria) {
      seriousnessCoding.push({
        system: "http://terminology.hl7.org/CodeSystem/adverse-event-seriousness",
        code: c,
        display: c.replace(/_/g, " "),
      });
    }
  } else if (report.isSerious) {
    seriousnessCoding.push({
      system: "http://terminology.hl7.org/CodeSystem/adverse-event-seriousness",
      code: "serious",
      display: "Serious Adverse Event",
    });
  }

  const fhirAdverseEvent = {
    resourceType: "AdverseEvent",
    id: `pharmaguard-${report._id}`,
    meta: {
      versionId: "1",
      lastUpdated: new Date().toISOString(),
      profile: ["http://hl7.org/fhir/StructureDefinition/AdverseEvent"],
    },
    identifier: [
      {
        system: "urn:ietf:rfc:3986",
        value: `urn:uuid:${report._id}`,
      },
    ],
    actuality: "actual",
    category: [
      {
        coding: [
          {
            system: "http://terminology.hl7.org/CodeSystem/adverse-event-category",
            code: "product-use-error",
            display: "Product Adverse Reaction",
          },
        ],
      },
    ],
    event: {
      coding: [
        {
          system: "http://hl7.org/fhir/sid/meddra",
          code: meddraEvent?.pt || "10000001",
          display: meddraEvent?.pt || primaryReaction,
        },
      ],
      text: symptoms.join(", ") || primaryReaction,
    },
    subject: {
      reference: `Patient/${report.fhirMetadata?.subjectIdentifier || "ANON-001"}`,
      display: report.fhirMetadata?.subjectIdentifier || "De-identified Patient",
    },
    date: report.createdAt ? report.createdAt.toISOString() : new Date().toISOString(),
    seriousness: {
      coding: seriousnessCoding.length > 0 ? seriousnessCoding : undefined,
    },
    severity: {
      coding: [
        {
          system: "http://terminology.hl7.org/CodeSystem/adverse-event-severity",
          code: classification?.severity || "moderate",
          display: (classification?.severity || "moderate").replace(/_/g, " "),
        },
      ],
    },
    suspectEntity: [
      {
        instance: {
          concept: {
            coding: [
              {
                system: "http://www.nlm.nih.gov/research/umls/rxnorm",
                code: rxNorm?.rxcui || "UNKNOWN",
                display: suspectDrugName,
              },
            ],
            text: suspectDrugName,
          },
          display: suspectDrugName,
        },
        causality: [
          {
            assessmentMethod: {
              coding: [
                {
                  system: "http://pharmaguard.ai/causality-method",
                  code: "naranjo-algorithm",
                  display: "Naranjo Adverse Drug Reaction Probability Scale",
                },
              ],
            },
            assessment: {
              coding: [
                {
                  system: "http://pharmaguard.ai/causality-result",
                  code: report.causality?.naranjoCategory || "Possible",
                  display: `Naranjo Score ${report.causality?.naranjoScore ?? 0} (${report.causality?.naranjoCategory || "Possible"})`,
                },
              ],
            },
          },
        ],
      },
    ],
    outcome: {
      coding: [
        {
          system: "http://terminology.hl7.org/CodeSystem/adverse-event-outcome",
          code: report.isSerious ? "recovering" : "resolved",
          display: report.isSerious ? "Recovering / Ongoing" : "Resolved",
        },
      ],
    },
    recorder: {
      display: report.submittedBy?.name || "Healthcare Professional",
    },
    note: [
      {
        text: report.summary || "PharmaGuard AI Pharmacovigilance Synthesized Case Summary",
      },
    ],
  };

  return fhirAdverseEvent;
}

/**
 * Returns FHIR CapabilityStatement for the PharmaGuard interoperability server.
 */
export function getFhirCapabilityStatement() {
  return {
    resourceType: "CapabilityStatement",
    id: "pharmaguard-fhir-capabilities",
    status: "active",
    date: new Date().toISOString(),
    publisher: "PharmaGuard AI Pharmacovigilance System",
    kind: "instance",
    software: {
      name: "PharmaGuard HL7 FHIR Interoperability Connector",
      version: "2.1.0",
    },
    fhirVersion: "4.0.1",
    format: ["application/fhir+json", "application/json"],
    rest: [
      {
        mode: "server",
        resource: [
          {
            type: "AdverseEvent",
            interaction: [{ code: "read" }, { code: "create" }, { code: "search-type" }],
            searchParam: [{ name: "_id", type: "token" }, { name: "subject", type: "reference" }],
          },
        ],
      },
    ],
  };
}
