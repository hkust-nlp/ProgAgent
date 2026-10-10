import argparse
import json
import os
import random
import sqlite3

import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 120,
    "num_workspace_files": 16,
}

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

DRUG_POOL = [
    {"drug_id": 1, "name": "Warfarin", "drug_class": "Anticoagulant"},
    {"drug_id": 2, "name": "Aspirin", "drug_class": "Antiplatelet"},
    {"drug_id": 3, "name": "Clopidogrel", "drug_class": "Antiplatelet"},
    {"drug_id": 4, "name": "Metformin", "drug_class": "Antidiabetic"},
    {"drug_id": 5, "name": "Lisinopril", "drug_class": "ACE_Inhibitor"},
    {"drug_id": 6, "name": "Amlodipine", "drug_class": "CCB"},
    {"drug_id": 7, "name": "Atorvastatin", "drug_class": "Statin"},
    {"drug_id": 8, "name": "Simvastatin", "drug_class": "Statin"},
    {"drug_id": 9, "name": "Omeprazole", "drug_class": "PPI"},
    {"drug_id": 10, "name": "Metoprolol", "drug_class": "Beta_Blocker"},
    {"drug_id": 11, "name": "Ciprofloxacin", "drug_class": "Fluoroquinolone"},
    {"drug_id": 12, "name": "Fluconazole", "drug_class": "Antifungal"},
    {"drug_id": 13, "name": "Ibuprofen", "drug_class": "NSAID"},
    {"drug_id": 14, "name": "Naproxen", "drug_class": "NSAID"},
    {"drug_id": 15, "name": "Prednisone", "drug_class": "Corticosteroid"},
    {"drug_id": 16, "name": "Furosemide", "drug_class": "Loop_Diuretic"},
    {"drug_id": 17, "name": "Spironolactone", "drug_class": "K_Sparing_Diuretic"},
    {"drug_id": 18, "name": "Digoxin", "drug_class": "Cardiac_Glycoside"},
    {"drug_id": 19, "name": "Amiodarone", "drug_class": "Antiarrhythmic"},
    {"drug_id": 20, "name": "Phenytoin", "drug_class": "Anticonvulsant"},
    {"drug_id": 21, "name": "Carbamazepine", "drug_class": "Anticonvulsant"},
    {"drug_id": 22, "name": "Lithium", "drug_class": "Mood_Stabilizer"},
    {"drug_id": 23, "name": "Gentamicin", "drug_class": "Aminoglycoside"},
    {"drug_id": 24, "name": "Vancomycin", "drug_class": "Glycopeptide"},
    {"drug_id": 25, "name": "Rifampin", "drug_class": "Antimycobacterial"},
    {"drug_id": 26, "name": "Erythromycin", "drug_class": "Macrolide"},
    {"drug_id": 27, "name": "Clarithromycin", "drug_class": "Macrolide"},
    {"drug_id": 28, "name": "Trimethoprim", "drug_class": "Antibiotic"},
    {"drug_id": 29, "name": "Diclofenac", "drug_class": "NSAID"},
    {"drug_id": 30, "name": "Ketoconazole", "drug_class": "Antifungal"},
    {"drug_id": 31, "name": "Levothyroxine", "drug_class": "Thyroid_Hormone"},
    {"drug_id": 32, "name": "Gabapentin", "drug_class": "Anticonvulsant"},
    {"drug_id": 33, "name": "Tramadol", "drug_class": "Opioid"},
    {"drug_id": 34, "name": "Methotrexate", "drug_class": "Immunosuppressant"},
    {"drug_id": 35, "name": "Allopurinol", "drug_class": "Antigout"},
    {"drug_id": 36, "name": "Citalopram", "drug_class": "SSRI"},
    {"drug_id": 37, "name": "Sertraline", "drug_class": "SSRI"},
    {"drug_id": 38, "name": "Duloxetine", "drug_class": "SNRI"},
    {"drug_id": 39, "name": "Pantoprazole", "drug_class": "PPI"},
    {"drug_id": 40, "name": "Doxycycline", "drug_class": "Tetracycline"},
]

CURATED_INTERACTIONS = [
    ("Warfarin", "Aspirin", "critical", "Significantly increased bleeding risk"),
    ("Warfarin", "Ibuprofen", "critical", "Increased bleeding and GI hemorrhage risk"),
    ("Warfarin", "Naproxen", "critical", "Increased bleeding and GI hemorrhage risk"),
    ("Warfarin", "Diclofenac", "critical", "Increased bleeding and GI hemorrhage risk"),
    ("Warfarin", "Ciprofloxacin", "major", "Enhanced anticoagulant effect - INR increase"),
    ("Warfarin", "Fluconazole", "major", "Enhanced anticoagulant effect - INR increase"),
    ("Warfarin", "Erythromycin", "major", "Enhanced anticoagulant effect - INR increase"),
    ("Warfarin", "Clarithromycin", "major", "Enhanced anticoagulant effect - INR increase"),
    ("Warfarin", "Rifampin", "major", "Reduced anticoagulant effect - subtherapeutic INR"),
    ("Warfarin", "Amiodarone", "major", "Enhanced anticoagulant effect - INR increase"),
    ("Warfarin", "Omeprazole", "moderate", "Possible increased INR"),
    ("Warfarin", "Simvastatin", "moderate", "Increased bleeding risk"),
    ("Warfarin", "Methotrexate", "major", "Increased methotrexate toxicity"),
    ("Warfarin", "Ketoconazole", "major", "Enhanced anticoagulant effect"),
    ("Digoxin", "Amiodarone", "critical", "Digoxin toxicity - reduce digoxin dose by 50%"),
    ("Digoxin", "Spironolactone", "major", "Increased digoxin serum levels"),
    ("Digoxin", "Clarithromycin", "major", "Increased digoxin levels via P-gp inhibition"),
    ("Digoxin", "Erythromycin", "major", "Increased digoxin levels via P-gp inhibition"),
    ("Digoxin", "Ketoconazole", "major", "Increased digoxin levels"),
    ("Digoxin", "Rifampin", "major", "Reduced digoxin levels - therapeutic failure risk"),
    ("Simvastatin", "Amiodarone", "critical", "Rhabdomyolysis risk - max simvastatin 20mg"),
    ("Simvastatin", "Clarithromycin", "critical", "Rhabdomyolysis risk - avoid combination"),
    ("Simvastatin", "Erythromycin", "major", "Increased statin levels - myopathy risk"),
    ("Simvastatin", "Fluconazole", "major", "Increased statin levels - myopathy risk"),
    ("Simvastatin", "Ketoconazole", "critical", "Rhabdomyolysis risk - avoid combination"),
    ("Simvastatin", "Amlodipine", "moderate", "Increased statin exposure - limit simvastatin dose"),
    ("Atorvastatin", "Clarithromycin", "major", "Increased statin levels - myopathy risk"),
    ("Atorvastatin", "Erythromycin", "moderate", "Possible increased statin levels"),
    ("Atorvastatin", "Ketoconazole", "major", "Increased statin levels - myopathy risk"),
    ("Atorvastatin", "Fluconazole", "moderate", "Possible increased statin levels"),
    ("Lithium", "Ibuprofen", "critical", "Lithium toxicity - NSAIDs reduce renal lithium clearance"),
    ("Lithium", "Naproxen", "critical", "Lithium toxicity - NSAIDs reduce renal lithium clearance"),
    ("Lithium", "Diclofenac", "critical", "Lithium toxicity - NSAIDs reduce renal lithium clearance"),
    ("Lithium", "Lisinopril", "major", "Increased lithium levels - monitor closely"),
    ("Lithium", "Furosemide", "major", "Increased lithium levels via sodium depletion"),
    ("Lithium", "Spironolactone", "moderate", "Possible increased lithium levels"),
    ("Metformin", "Ciprofloxacin", "moderate", "Blood glucose disturbances"),
    ("Phenytoin", "Fluconazole", "major", "Increased phenytoin levels - toxicity risk"),
    ("Phenytoin", "Omeprazole", "moderate", "Altered phenytoin metabolism"),
    ("Phenytoin", "Trimethoprim", "moderate", "Increased phenytoin levels"),
    ("Carbamazepine", "Erythromycin", "critical", "Carbamazepine toxicity - CYP3A4 inhibition"),
    ("Carbamazepine", "Clarithromycin", "critical", "Carbamazepine toxicity - CYP3A4 inhibition"),
    ("Carbamazepine", "Fluconazole", "major", "Increased carbamazepine levels"),
    ("Carbamazepine", "Ketoconazole", "major", "Increased carbamazepine levels"),
    ("Spironolactone", "Lisinopril", "major", "Hyperkalemia risk - monitor potassium"),
    ("Spironolactone", "Trimethoprim", "major", "Hyperkalemia risk - monitor potassium"),
    ("Gentamicin", "Furosemide", "major", "Increased ototoxicity and nephrotoxicity"),
    ("Vancomycin", "Gentamicin", "major", "Additive nephrotoxicity"),
    ("Ciprofloxacin", "Prednisone", "moderate", "Increased tendon rupture risk"),
    ("Aspirin", "Clopidogrel", "major", "Increased bleeding risk"),
    ("Aspirin", "Ibuprofen", "moderate", "Reduced cardioprotective effect of aspirin"),
    ("Aspirin", "Naproxen", "moderate", "Possible reduced aspirin antiplatelet effect"),
    ("Prednisone", "Ibuprofen", "major", "Increased GI bleeding risk"),
    ("Prednisone", "Naproxen", "major", "Increased GI bleeding risk"),
    ("Prednisone", "Diclofenac", "major", "Increased GI bleeding risk"),
    ("Rifampin", "Simvastatin", "major", "Reduced statin levels - therapeutic failure"),
    ("Rifampin", "Atorvastatin", "major", "Reduced statin levels - therapeutic failure"),
    ("Rifampin", "Amlodipine", "moderate", "Reduced amlodipine levels"),
    ("Rifampin", "Metoprolol", "moderate", "Reduced metoprolol levels"),
    ("Rifampin", "Omeprazole", "moderate", "Reduced omeprazole levels"),
    ("Amiodarone", "Phenytoin", "major", "Increased phenytoin levels"),
    ("Amiodarone", "Carbamazepine", "moderate", "Altered carbamazepine levels"),
    ("Clarithromycin", "Amiodarone", "major", "QT prolongation risk"),
    ("Erythromycin", "Amiodarone", "major", "QT prolongation risk"),
    ("Metoprolol", "Amiodarone", "major", "Severe bradycardia risk"),
    ("Citalopram", "Tramadol", "major", "Serotonin syndrome risk"),
    ("Sertraline", "Tramadol", "major", "Serotonin syndrome risk"),
    ("Duloxetine", "Tramadol", "major", "Serotonin syndrome risk"),
    ("Methotrexate", "Trimethoprim", "critical", "Methotrexate toxicity - bone marrow suppression"),
    ("Methotrexate", "Ibuprofen", "major", "Increased methotrexate levels - toxicity risk"),
    ("Methotrexate", "Naproxen", "major", "Increased methotrexate levels - toxicity risk"),
    ("Allopurinol", "Methotrexate", "major", "Increased methotrexate toxicity"),
    ("Vancomycin", "Furosemide", "moderate", "Increased nephrotoxicity risk"),
    ("Citalopram", "Erythromycin", "major", "QT prolongation risk"),
    ("Citalopram", "Clarithromycin", "major", "QT prolongation risk"),
    ("Furosemide", "Digoxin", "moderate", "Hypokalemia may increase digoxin toxicity"),
    ("Sertraline", "Warfarin", "moderate", "Possible increased bleeding risk"),
    ("Duloxetine", "Warfarin", "moderate", "Possible increased bleeding risk"),
]

DIAGNOSIS_POOL = [
    ("I10", "Essential Hypertension"),
    ("E11.9", "Type 2 Diabetes Mellitus"),
    ("I48.91", "Atrial Fibrillation"),
    ("I50.9", "Heart Failure"),
    ("J44.1", "COPD"),
    ("J45.20", "Asthma"),
    ("N18.3", "Chronic Kidney Disease Stage 3"),
    ("N18.4", "Chronic Kidney Disease Stage 4"),
    ("K74.60", "Hepatic Cirrhosis"),
    ("G40.909", "Epilepsy"),
    ("M10.9", "Gout"),
    ("K27.9", "Peptic Ulcer Disease"),
    ("I82.90", "Deep Vein Thrombosis"),
    ("E03.9", "Hypothyroidism"),
    ("F31.9", "Bipolar Disorder"),
    ("J18.9", "Pneumonia"),
    ("I25.10", "Coronary Artery Disease"),
    ("E78.5", "Hyperlipidemia"),
    ("K21.0", "GERD"),
    ("M81.0", "Osteoporosis"),
]

CONTRAINDICATION_RULES = [
    {"drug": "Metformin", "condition_code": "N18.4", "condition": "Chronic Kidney Disease Stage 4",
     "severity": "critical", "reason": "Risk of lactic acidosis with severe renal impairment"},
    {"drug": "Ibuprofen", "condition_code": "K27.9", "condition": "Peptic Ulcer Disease",
     "severity": "critical", "reason": "High risk of GI bleeding with active peptic ulcer"},
    {"drug": "Naproxen", "condition_code": "K27.9", "condition": "Peptic Ulcer Disease",
     "severity": "critical", "reason": "High risk of GI bleeding with active peptic ulcer"},
    {"drug": "Diclofenac", "condition_code": "K27.9", "condition": "Peptic Ulcer Disease",
     "severity": "critical", "reason": "High risk of GI bleeding with active peptic ulcer"},
    {"drug": "Metoprolol", "condition_code": "J45.20", "condition": "Asthma",
     "severity": "major", "reason": "Beta-blockers may cause bronchospasm in asthma patients"},
    {"drug": "Ibuprofen", "condition_code": "N18.3", "condition": "Chronic Kidney Disease Stage 3",
     "severity": "major", "reason": "NSAIDs may worsen renal function in CKD"},
    {"drug": "Naproxen", "condition_code": "N18.3", "condition": "Chronic Kidney Disease Stage 3",
     "severity": "major", "reason": "NSAIDs may worsen renal function in CKD"},
    {"drug": "Diclofenac", "condition_code": "N18.3", "condition": "Chronic Kidney Disease Stage 3",
     "severity": "major", "reason": "NSAIDs may worsen renal function in CKD"},
    {"drug": "Ibuprofen", "condition_code": "N18.4", "condition": "Chronic Kidney Disease Stage 4",
     "severity": "critical", "reason": "NSAIDs contraindicated in severe renal impairment"},
    {"drug": "Naproxen", "condition_code": "N18.4", "condition": "Chronic Kidney Disease Stage 4",
     "severity": "critical", "reason": "NSAIDs contraindicated in severe renal impairment"},
    {"drug": "Diclofenac", "condition_code": "N18.4", "condition": "Chronic Kidney Disease Stage 4",
     "severity": "critical", "reason": "NSAIDs contraindicated in severe renal impairment"},
    {"drug": "Lithium", "condition_code": "N18.3", "condition": "Chronic Kidney Disease Stage 3",
     "severity": "major", "reason": "Lithium accumulation risk with impaired renal function"},
    {"drug": "Lithium", "condition_code": "N18.4", "condition": "Chronic Kidney Disease Stage 4",
     "severity": "critical", "reason": "Severe lithium accumulation risk"},
    {"drug": "Gentamicin", "condition_code": "N18.3", "condition": "Chronic Kidney Disease Stage 3",
     "severity": "major", "reason": "Increased nephrotoxicity risk with aminoglycosides"},
    {"drug": "Gentamicin", "condition_code": "N18.4", "condition": "Chronic Kidney Disease Stage 4",
     "severity": "critical", "reason": "Aminoglycosides contraindicated in severe CKD"},
    {"drug": "Spironolactone", "condition_code": "N18.4", "condition": "Chronic Kidney Disease Stage 4",
     "severity": "major", "reason": "Hyperkalemia risk in severe renal impairment"},
    {"drug": "Prednisone", "condition_code": "E11.9", "condition": "Type 2 Diabetes Mellitus",
     "severity": "moderate", "reason": "Corticosteroids impair glycemic control"},
    {"drug": "Ciprofloxacin", "condition_code": "G40.909", "condition": "Epilepsy",
     "severity": "moderate", "reason": "Fluoroquinolones may lower seizure threshold"},
    {"drug": "Digoxin", "condition_code": "N18.4", "condition": "Chronic Kidney Disease Stage 4",
     "severity": "major", "reason": "Digoxin accumulation with impaired renal clearance"},
    {"drug": "Methotrexate", "condition_code": "K74.60", "condition": "Hepatic Cirrhosis",
     "severity": "critical", "reason": "Methotrexate hepatotoxicity contraindicated in liver disease"},
    {"drug": "Methotrexate", "condition_code": "N18.3", "condition": "Chronic Kidney Disease Stage 3",
     "severity": "major", "reason": "Methotrexate accumulation with renal impairment"},
    {"drug": "Methotrexate", "condition_code": "N18.4", "condition": "Chronic Kidney Disease Stage 4",
     "severity": "critical", "reason": "Severe methotrexate toxicity risk with CKD stage 4"},
]

LAB_TESTS = [
    {"name": "INR", "unit": "ratio", "normal_low": 0.8, "normal_high": 1.2},
    {"name": "Serum Creatinine", "unit": "mg/dL", "normal_low": 0.6, "normal_high": 1.2},
    {"name": "Potassium", "unit": "mEq/L", "normal_low": 3.5, "normal_high": 5.0},
    {"name": "ALT", "unit": "U/L", "normal_low": 7.0, "normal_high": 56.0},
    {"name": "AST", "unit": "U/L", "normal_low": 10.0, "normal_high": 40.0},
    {"name": "Blood Glucose", "unit": "mg/dL", "normal_low": 70.0, "normal_high": 100.0},
    {"name": "Hemoglobin", "unit": "g/dL", "normal_low": 12.0, "normal_high": 17.5},
    {"name": "Platelet Count", "unit": "x10^3/uL", "normal_low": 150.0, "normal_high": 400.0},
    {"name": "Sodium", "unit": "mEq/L", "normal_low": 136.0, "normal_high": 145.0},
    {"name": "eGFR", "unit": "mL/min/1.73m2", "normal_low": 60.0, "normal_high": 120.0},
]

ALERT_THRESHOLD_RULES = [
    {
        "test_name": "INR",
        "relevant_drugs": ["Warfarin"],
        "thresholds": {"critical_high": 5.0, "major_high": 4.0, "moderate_high": 3.5},
        "description": "Elevated INR in anticoagulated patient",
    },
    {
        "test_name": "Potassium",
        "relevant_drugs": ["Spironolactone", "Lisinopril", "Trimethoprim"],
        "thresholds": {"critical_high": 6.0, "major_high": 5.5},
        "description": "Hyperkalemia risk with potassium-affecting medication",
    },
    {
        "test_name": "Potassium",
        "relevant_drugs": ["Furosemide"],
        "thresholds": {"critical_low": 2.5, "major_low": 3.0},
        "description": "Hypokalemia risk with loop diuretic",
    },
    {
        "test_name": "Serum Creatinine",
        "relevant_drugs": ["Metformin", "Gentamicin", "Vancomycin", "Lithium", "Digoxin"],
        "thresholds": {"critical_high": 4.0, "major_high": 2.5, "moderate_high": 1.8},
        "description": "Renal impairment concern with renally-cleared medication",
    },
    {
        "test_name": "ALT",
        "relevant_drugs": ["Atorvastatin", "Simvastatin", "Phenytoin", "Carbamazepine",
                           "Ketoconazole", "Methotrexate"],
        "thresholds": {"critical_high": 200.0, "major_high": 120.0},
        "description": "Hepatotoxicity concern with hepatically-metabolized medication",
    },
    {
        "test_name": "Platelet Count",
        "relevant_drugs": ["Warfarin", "Aspirin", "Clopidogrel"],
        "thresholds": {"critical_low": 50.0, "major_low": 100.0},
        "description": "Thrombocytopenia risk in patient on anticoagulant or antiplatelet",
    },
    {
        "test_name": "Blood Glucose",
        "relevant_drugs": ["Metformin"],
        "thresholds": {"critical_low": 54.0, "major_low": 70.0},
        "description": "Hypoglycemia risk in patient on glucose-lowering agent",
    },
]

SEVERITY_PROTOCOL = """# Patient Safety Alert Response Protocol

## Severity Levels and Required Actions

Critical: Requires immediate pharmacist intervention within one hour.
Recommended action: "Immediate pharmacist review - hold medication and contact prescriber urgently"

Major: Requires pharmacist review within four hours.
Recommended action: "Pharmacist review required - contact prescriber for order modification"

Moderate: Should be addressed during the next scheduled pharmacist review within twenty-four hours.
Recommended action: "Flag for pharmacist review at next scheduled assessment"

Minor: Informational alerts logged for pharmacist awareness.
Recommended action: "Document in patient record for pharmacist awareness"

## Alert Generation Methodology

See alert_generation_methodology.md for the authoritative definitions of the
four alert categories and their evaluation rules.

## Monitoring Level Alert Thresholds

Patients assigned an "intensive" monitoring level receive alerts at all severity levels: critical, major, moderate, and minor.

Patients assigned an "enhanced" monitoring level receive alerts at severity levels: critical, major, and moderate only.

Patients assigned a "standard" monitoring level receive alerts only at severity levels: critical and major.

## Alert Prioritization for Daily Report

When compiling the daily alert list, alerts must be ordered by severity from highest to lowest: critical first, then major, then moderate, then minor. Within the same severity level, sort alphabetically by patient last name, then by first name. If a patient has multiple alerts at the same severity level, each alert appears as a separate row, further sorted by alert type alphabetically (contraindication, drug_allergy, drug_interaction, lab_alert).
"""

ALERT_METHODOLOGY = """# Alert Generation Methodology

This document is the authoritative specification for how safety alerts are
generated for the daily patient safety alert report. It is used together with
the severity response protocol, the contraindication reference, the laboratory
alert threshold configuration, the ward rosters, and the nursing allergy
records.

## 1. Drug-Drug Interaction Alerts (alert_type: drug_interaction)

An alert is generated whenever a patient is concurrently dispensed two
medications that appear together as a pair in the hospital's drug interaction
database. "Concurrently dispensed" means both drugs appear among the patient's
current dispensing records. Each unique drug pair for a patient produces
exactly one alert, regardless of how many interaction records reference the
pair or in which order the two drugs are recorded. The alert's severity and
description come directly from the interaction database record for that pair.

## 2. Contraindication Alerts (alert_type: contraindication)

An alert is generated when a patient carries an active diagnosis whose ICD
code matches the condition code of a rule in the contraindication reference
AND the patient is currently dispensed the drug cited in that same rule. The
alert's severity is specified by the rule, and its description is the rule's
stated reason. Each matching rule produces its own alert.

## 3. Laboratory Value Alerts (alert_type: lab_alert)

For each rule in the laboratory alert threshold configuration, an alert is
evaluated only when the patient is currently dispensed at least one of the
drugs listed as relevant for that rule. Only the patient's MOST RECENT result
for the rule's test (the result with the latest result date) is evaluated.

Threshold boundaries are inclusive: a high band is triggered when the value is
greater than or equal to the band's threshold, and a low band is triggered
when the value is less than or equal to the band's threshold. Within the high
bands the most severe band that the value reaches determines the severity
(critical over major over moderate); the low bands work the same way. If both
a high band and a low band are triggered, the more severe of the two
classifications applies.

If the patient is currently taking more than one relevant drug from the same
rule, each such drug produces its own separate alert entry. The alert's
description is the rule's description.

## 4. Drug-Allergy Alerts (alert_type: drug_allergy)

An alert is generated whenever a patient is currently dispensed a drug to
which they have a documented allergy in the nursing department's allergy
records. Every drug-allergy alert is classified at critical severity, with a
description noting the specific conflict.

## Monitoring-Level Filtering

Every generated alert is then filtered by the patient's assigned monitoring
level as recorded in the ward rosters. The severity response protocol defines
which severity levels are included under each monitoring level; an alert whose
severity falls outside the patient's permitted set is excluded from the
report.

## Recommended Actions

The recommended_action for each alert must use the exact phrasing defined in
the severity response protocol for the alert's severity level.
"""


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------

def main(db_path, workspace):
    random.seed(42)
    np.random.seed(42)
    fake = Faker("en_US")
    Faker.seed(42)

    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    n_patients = SCALE["rows_per_table"]
    n_ward_files = SCALE["num_workspace_files"] // 2
    n_allergy_files = SCALE["num_workspace_files"] - n_ward_files

    # -----------------------------------------------------------------------
    # Create tables
    # -----------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            patient_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name  TEXT NOT NULL,
            date_of_birth TEXT NOT NULL,
            gender TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dispensing_records (
            record_id  INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            drug_name  TEXT NOT NULL,
            dose       TEXT NOT NULL,
            frequency  TEXT NOT NULL,
            dispensed_date TEXT NOT NULL,
            prescriber TEXT NOT NULL,
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS drug_interactions (
            interaction_id INTEGER PRIMARY KEY,
            drug_a      TEXT NOT NULL,
            drug_b      TEXT NOT NULL,
            severity    TEXT NOT NULL,
            description TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS diagnoses (
            diagnosis_id  INTEGER PRIMARY KEY,
            patient_id    INTEGER NOT NULL,
            icd_code      TEXT NOT NULL,
            diagnosis_name TEXT NOT NULL,
            status        TEXT NOT NULL,
            diagnosed_date TEXT NOT NULL,
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lab_results (
            result_id   INTEGER PRIMARY KEY,
            patient_id  INTEGER NOT NULL,
            test_name   TEXT NOT NULL,
            test_value  REAL NOT NULL,
            unit        TEXT NOT NULL,
            result_date TEXT NOT NULL,
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    """)

    # -----------------------------------------------------------------------
    # Generate patients
    # -----------------------------------------------------------------------
    patients = []
    for i in range(1, n_patients + 1):
        fn = fake.first_name()
        ln = fake.last_name()
        dob = str(fake.date_of_birth(minimum_age=18, maximum_age=90))
        gender = random.choice(["M", "F"])
        patients.append((i, fn, ln, dob, gender))
    cur.executemany("INSERT INTO patients VALUES (?,?,?,?,?)", patients)

    # -----------------------------------------------------------------------
    # Generate dispensing records  (2-4 drugs per patient)
    # -----------------------------------------------------------------------
    drug_names = [d["name"] for d in DRUG_POOL]
    patient_drug_map = {}
    disp_records = []
    rid = 1
    doses = ["5mg", "10mg", "20mg", "25mg", "50mg", "100mg", "200mg", "250mg", "500mg"]
    freqs = ["once daily", "twice daily", "three times daily", "every 8 hours",
             "every 12 hours"]

    for pid in range(1, n_patients + 1):
        n_drugs = random.randint(2, 4)
        selected_drugs = random.sample(drug_names, n_drugs)
        patient_drug_map[pid] = selected_drugs
        for drug in selected_drugs:
            dose = random.choice(doses)
            freq = random.choice(freqs)
            disp_date = str(fake.date_between(start_date="-30d", end_date="today"))
            prescriber = f"Dr. {fake.last_name()}"
            disp_records.append((rid, pid, drug, dose, freq, disp_date, prescriber))
            rid += 1
    cur.executemany("INSERT INTO dispensing_records VALUES (?,?,?,?,?,?,?)", disp_records)

    # -----------------------------------------------------------------------
    # Generate drug interactions  (curated + padding to reach SCALE)
    # -----------------------------------------------------------------------
    interactions = []
    iid = 1
    existing_pairs = set()
    for drug_a, drug_b, severity, desc in CURATED_INTERACTIONS:
        pair_key = tuple(sorted([drug_a, drug_b]))
        if pair_key not in existing_pairs:
            interactions.append((iid, drug_a, drug_b, severity, desc))
            existing_pairs.add(pair_key)
            iid += 1

    if len(interactions) < SCALE["rows_per_table"]:
        candidate_pairs = []
        for i in range(len(drug_names)):
            for j in range(i + 1, len(drug_names)):
                pk = tuple(sorted([drug_names[i], drug_names[j]]))
                if pk not in existing_pairs:
                    candidate_pairs.append(pk)
        random.shuffle(candidate_pairs)
        minor_descs = [
            "Possible pharmacokinetic interaction - monitor patient",
            "Theoretical interaction - clinical significance uncertain",
            "Minor additive effects - routine monitoring recommended",
            "Potential interaction - use with caution",
        ]
        idx = 0
        while len(interactions) < SCALE["rows_per_table"] and idx < len(candidate_pairs):
            pair = candidate_pairs[idx]
            interactions.append(
                (iid, pair[0], pair[1], "minor", random.choice(minor_descs)))
            existing_pairs.add(pair)
            iid += 1
            idx += 1
    cur.executemany("INSERT INTO drug_interactions VALUES (?,?,?,?,?)", interactions)

    # -----------------------------------------------------------------------
    # Generate diagnoses  (1-3 per patient)
    # -----------------------------------------------------------------------
    diag_records = []
    patient_diag_map = {}
    did = 1
    for pid in range(1, n_patients + 1):
        n_diag = random.randint(1, 3)
        selected = random.sample(DIAGNOSIS_POOL, n_diag)
        patient_diag_map[pid] = selected
        for code, name in selected:
            diag_date = str(fake.date_between(start_date="-365d", end_date="-30d"))
            diag_records.append((did, pid, code, name, "active", diag_date))
            did += 1

    attempts = 0
    while len(diag_records) < SCALE["rows_per_table"] and attempts < 1000:
        extra_pid = random.randint(1, n_patients)
        code, name = random.choice(DIAGNOSIS_POOL)
        existing_codes = {d[2] for d in diag_records if d[1] == extra_pid}
        if code not in existing_codes:
            diag_date = str(fake.date_between(start_date="-365d", end_date="-30d"))
            diag_records.append((did, extra_pid, code, name, "active", diag_date))
            patient_diag_map.setdefault(extra_pid, []).append((code, name))
            did += 1
        attempts += 1
    cur.executemany("INSERT INTO diagnoses VALUES (?,?,?,?,?,?)", diag_records)

    # -----------------------------------------------------------------------
    # Generate lab results  (2-4 distinct tests per patient)
    # -----------------------------------------------------------------------
    lab_records = []
    lid = 1
    for pid in range(1, n_patients + 1):
        n_tests = random.randint(2, 4)
        selected_tests = random.sample(LAB_TESTS, n_tests)
        for test in selected_tests:
            if random.random() < 0.25:
                if random.random() < 0.5:
                    value = test["normal_high"] * random.uniform(1.1, 3.0)
                else:
                    value = test["normal_low"] * random.uniform(0.2, 0.9)
            else:
                value = random.uniform(test["normal_low"], test["normal_high"])
            value = round(value, 2)
            result_date = str(fake.date_between(start_date="-7d", end_date="today"))
            lab_records.append(
                (lid, pid, test["name"], value, test["unit"], result_date))
            lid += 1

    while len(lab_records) < SCALE["rows_per_table"]:
        extra_pid = random.randint(1, n_patients)
        test = random.choice(LAB_TESTS)
        value = round(random.uniform(test["normal_low"], test["normal_high"]), 2)
        result_date = str(fake.date_between(start_date="-7d", end_date="today"))
        lab_records.append(
            (lid, extra_pid, test["name"], value, test["unit"], result_date))
        lid += 1
    cur.executemany("INSERT INTO lab_results VALUES (?,?,?,?,?,?)", lab_records)

    conn.commit()
    conn.close()

    # -----------------------------------------------------------------------
    # Workspace - fixed files
    # -----------------------------------------------------------------------
    with open(os.path.join(workspace, "contraindications.json"), "w") as f:
        json.dump(CONTRAINDICATION_RULES, f, indent=2)

    # alert_thresholds.yaml  (written as formatted text)
    yaml_lines = ["lab_alert_rules:"]
    for rule in ALERT_THRESHOLD_RULES:
        yaml_lines.append(f'  - test_name: "{rule["test_name"]}"')
        yaml_lines.append("    relevant_drugs:")
        for drug in rule["relevant_drugs"]:
            yaml_lines.append(f'      - "{drug}"')
        yaml_lines.append("    thresholds:")
        for k, v in rule["thresholds"].items():
            yaml_lines.append(f"      {k}: {v}")
        yaml_lines.append(f'    description: "{rule["description"]}"')
    with open(os.path.join(workspace, "alert_thresholds.yaml"), "w") as f:
        f.write("\n".join(yaml_lines) + "\n")

    with open(os.path.join(workspace, "severity_response_protocol.md"), "w") as f:
        f.write(SEVERITY_PROTOCOL)

    with open(os.path.join(workspace, "alert_generation_methodology.md"), "w") as f:
        f.write(ALERT_METHODOLOGY)

    # -----------------------------------------------------------------------
    # Workspace - scalable ward roster CSVs
    # -----------------------------------------------------------------------
    ward_names = [f"Ward_{i + 1:02d}" for i in range(n_ward_files)]
    ward_data = {w: [] for w in ward_names}

    for pid in range(1, n_patients + 1):
        widx = (pid - 1) % n_ward_files
        ward = ward_names[widx]
        bed = f"{widx + 1}-{((pid - 1) // n_ward_files) + 1:03d}"
        monitoring = random.choice(["standard", "enhanced", "intensive"])
        p = patients[pid - 1]
        ward_data[ward].append({
            "patient_id": pid,
            "patient_name": f"{p[2]}, {p[1]}",
            "ward": ward,
            "bed": bed,
            "monitoring_level": monitoring,
        })

    for ward_name in ward_names:
        df = pd.DataFrame(ward_data[ward_name])
        fname = f"{ward_name.lower()}_roster.csv"
        df.to_csv(os.path.join(workspace, fname), index=False)

    # -----------------------------------------------------------------------
    # Workspace - scalable allergy record JSONs
    # -----------------------------------------------------------------------
    patient_allergies = {}
    for pid in range(1, n_patients + 1):
        if random.random() < 0.4:
            n_allerg = random.randint(1, 3)
            patient_allergies[pid] = random.sample(drug_names, n_allerg)

    allergy_items = sorted(patient_allergies.items())
    allergy_file_data = [[] for _ in range(n_allergy_files)]
    for idx, (pid, allergies) in enumerate(allergy_items):
        file_idx = idx % n_allergy_files
        allergy_file_data[file_idx].append({"patient_id": pid, "allergies": allergies})

    for i in range(n_allergy_files):
        fname = f"allergy_records_batch_{i + 1:02d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(allergy_file_data[i], f, indent=2)

    print(f"Database created at {db_path} with {n_patients} patients")
    print(f"Workspace created in {workspace}/ "
          f"({4 + n_ward_files + n_allergy_files} files)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
