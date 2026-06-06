# NORTHWIND LOGISTICS SOFTWARE, INC.
## SUB-PROCESSOR REGISTER & DATA-FLOW INVENTORY

**Document Classification:** Internal / Confidential
**Maintained by:** Data Protection & Security Office
**Period:** 2026-Q1 (as of March 31, 2026)
**Document Owner:** Data Protection Officer (DPO), Northwind Logistics Software, Inc.
**Review cycle:** Quarterly

---

## 1. PURPOSE

This register inventories all third-party sub-processors engaged by Northwind Logistics Software, Inc. ("Northwind") that process personal data on Northwind's behalf in connection with its freight transportation-management (TMS) SaaS platform. It is maintained to support Northwind's obligations under Article 28 and Article 30 of the EU General Data Protection Regulation (GDPR) and to track the contractual basis and international-transfer mechanism for each engagement.

This register also serves as the data-flow reference used to verify that customer-specific Data Processing Agreements (DPAs) accurately list the sub-processors that touch each customer's personal data.

---

## 2. KEY CUSTOMER DATA CONTEXT

- **Tidewater Distribution N.V.** ("Tidewater") is an EU customer established in Belgium. Personal data processed on Tidewater's behalf includes **driver identity and contact data, driver location/telemetry data, and consignee (recipient) contact details** — all of which constitute personal data of EU data subjects under GDPR.
- The Tidewater Master Services Agreement incorporates a Data Processing Agreement ("**Tidewater DPA**") executed 2024-09-12. **Annex 2** of the Tidewater DPA contains the list of sub-processors approved to process Tidewater personal data, together with the applicable transfer mechanism for any processing outside the EEA.
- Any sub-processor that processes Tidewater personal data **must** appear in Tidewater DPA Annex 2, and any transfer of such data outside the EEA **must** be covered by an approved transfer mechanism (e.g., EU Standard Contractual Clauses ("SCCs") or an adequacy decision).

---

## 3. SUB-PROCESSOR INVENTORY

Legend for "Covers Tidewater EU data?": **Listed** = named in Tidewater DPA Annex 2; **NOT LISTED** = processes Tidewater personal data but absent from Annex 2.

| # | Sub-Processor | Service Provided | Personal Data Categories Processed | Hosting Location | Processes Tidewater EU Data? | Listed in Tidewater DPA Annex 2? | Contract / SCC Status |
|---|---------------|------------------|------------------------------------|------------------|------------------------------|----------------------------------|------------------------|
| 1 | **CloudHarbor EU GmbH** | Primary cloud infrastructure / application hosting | Driver identity & contact data, consignee contact data, shipment records | Frankfurt, Germany (EEA) | Yes | **Listed** | DPA executed 2024-08-01; intra-EEA, no transfer mechanism required |
| 2 | **MessageRoute SAS** | Transactional email & SMS dispatch notifications | Driver name, driver phone/email, consignee phone/email | Paris, France (EEA) | Yes | **Listed** | DPA executed 2024-08-15; intra-EEA |
| 3 | **TelemetryWorks Inc.** | Real-time vehicle telemetry ingestion, route-performance analytics, and event monitoring | **Driver location/GPS telemetry, driver identifier, vehicle/trip metadata, timestamps** | **Portland, Oregon, USA** | **Yes** | **NOT LISTED** | **SCCs: none on file. No DPA executed with Northwind covering EU data. No adequacy basis. Transfer mechanism: NONE.** |
| 4 | **LedgerPay Ltd.** | Subscription billing & payment processing (Northwind's own billing) | Northwind customer-admin billing contacts only (no driver/consignee data) | Dublin, Ireland (EEA) | No | N/A | DPA executed 2024-07-20; processes Northwind account data only |
| 5 | **HelpDeskNow Inc.** | Customer support ticketing for Northwind admin users | Northwind customer-admin support contacts; incidental driver data if pasted into tickets | Virginia, USA | Limited / incidental | Partially — listed for admin support only | SCCs (2021 EU module) executed 2024-10-05; covers admin-contact data; driver telemetry out of scope |
| 6 | **ArchiveVault EU** | Encrypted backup & disaster-recovery storage | Encrypted snapshots of all production data (incl. Tidewater data at rest) | Amsterdam, Netherlands (EEA) | Yes (encrypted at rest) | **Listed** | DPA executed 2024-08-01; intra-EEA |

---

## 4. FLAGGED GAP — ROW 3 (TelemetryWorks Inc.)

**Status: OPEN — unresolved as of 2026-Q1 review.**

4.1 **What is happening.** Northwind's platform streams real-time driver location/GPS telemetry and trip metadata for Tidewater's fleet to **TelemetryWorks Inc.**, a sub-processor hosted in Portland, Oregon, USA. TelemetryWorks performs route-performance analytics and event monitoring on this data. This data flow is active in production for the Tidewater tenant.

4.2 **The compliance gaps.**

- **(a) Annex 2 omission.** TelemetryWorks does **not** appear in the Tidewater DPA Annex 2 list of approved sub-processors. Tidewater has therefore not been notified of, and has not approved, this sub-processor as required under Section 5 (Sub-Processing) of the Tidewater DPA.
- **(b) No transfer mechanism for US transfer.** The telemetry data is personal data of EU data subjects (Belgian drivers) transferred from the EEA to the United States. **No EU Standard Contractual Clauses (SCCs) are on file**, no EU–US Data Privacy Framework certification has been verified for TelemetryWorks, and no other Article 46 transfer mechanism is in place. The US transfer currently has **no lawful transfer basis** documented.
- **(c) No executed DPA.** There is no Article 28 data-processing agreement on file between Northwind and TelemetryWorks covering EU personal data.

4.3 **Data subjects affected.** EU drivers (Belgium) whose location/telemetry is processed for the Tidewater tenant. Approximate scope: all active Tidewater fleet drivers transmitting telemetry during the period.

4.4 **Internal note.** TelemetryWorks was onboarded by the Platform Engineering team in 2025 to improve route-ETA accuracy; the engagement was not routed through the DPO sub-processor-approval workflow, which is why it is absent from both this register's prior revisions and the Tidewater DPA Annex 2. Flagged here for remediation tracking.

---

## 5. REMEDIATION TRACKING (informational)

| Item | Owner | Target | Status |
|------|-------|--------|--------|
| Execute SCCs (EU 2021 modules, controller-to-processor) with TelemetryWorks | DPO / Legal | TBD | Not started |
| Execute Article 28 DPA with TelemetryWorks | Legal | TBD | Not started |
| Notify Tidewater & update DPA Annex 2 (sub-processor change procedure) | DPO | TBD | Not started |
| Assess transfer-impact assessment (TIA) for US telemetry transfer | DPO | TBD | Not started |
| Confirm whether telemetry can be re-routed to EEA-hosted analytics | Platform Engineering | TBD | Under discussion |

---

## 6. ATTESTATION

This register reflects the sub-processors known to the Data Protection & Security Office as of March 31, 2026. The gap recorded in Section 4 is unresolved and is included in the data-room disclosure for transparency.

_Prepared by: Data Protection & Security Office, Northwind Logistics Software, Inc._
_Period: 2026-Q1 — as of 31 March 2026_
