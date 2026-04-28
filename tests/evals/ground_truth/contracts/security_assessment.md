# Annual Security Assessment Report

**Prepared for:** Company A ("Target")
**Assessment Date:** March 15, 2024
**Assessor:** Security Audit Group ("Assessor")
**Report Version:** 1.0

## Section 1 — Executive Summary

This report presents findings from the annual security assessment of Company A's
information systems, policies, and practices. The assessment covered infrastructure,
application security, access controls, compliance posture, and incident response
capabilities.

Overall maturity rating: **Developing** (Level 2 of 5)

## Section 2 — Compliance Certifications

2.1 Company A holds SOC 2 Type II certification, issued June 2022. The certification
**expired on June 30, 2023** and has not been renewed as of the assessment date.

2.2 Company A does not hold ISO 27001 certification. An ISO 27001 readiness
assessment was initiated in Q3 2023 but was paused due to resource constraints.

2.3 Company A is not PCI DSS certified. Payment processing is handled by a
third-party payment processor (Vendor X).

## Section 3 — Access Controls

3.1 Multi-factor authentication (MFA) is enforced for VPN access and cloud
administration console. **MFA is NOT enforced for general employee access to
the primary SaaS application or email systems.**

3.2 Role-based access control (RBAC) is implemented for the production application.
Access reviews are conducted annually. The most recent access review was completed
in January 2023 (over 12 months ago as of assessment date).

3.3 Privileged access management: 14 employees have administrative access to
production systems. There is no dedicated PAM solution; administrative credentials
are stored in a shared password manager. No session recording is implemented for
privileged access.

## Section 4 — Encryption Standards

4.1 Data in transit: All external communications use TLS 1.2. Internal
service-to-service communication within the production VPC uses TLS 1.2.

4.2 **Data at rest: Customer data stored in the primary database (PostgreSQL) is
NOT encrypted at rest.** Application-level encryption is applied to a subset of
fields classified as "highly sensitive" (credit card tokens, SSNs), but general
customer data including names, email addresses, usage data, and contract terms
is stored in plaintext.

4.3 Backup encryption: Database backups are encrypted using AES-256. Backup
encryption keys are rotated annually.

## Section 5 — Vulnerability Management

5.1 External vulnerability scans are performed quarterly by Vendor Y. The most
recent scan (December 2023) identified 3 critical vulnerabilities (CVSS >= 9.0),
12 high vulnerabilities (CVSS 7.0-8.9), and 47 medium vulnerabilities.

5.2 Of the 3 critical vulnerabilities identified in December 2023, **2 remain
unpatched as of the assessment date** (March 2024). These affect the public-facing
web application server (CVE-2023-44487, CVE-2023-46604).

5.3 Penetration testing: The most recent external penetration test was conducted
in September 2022 (18 months ago). Industry best practice recommends annual
penetration testing.

## Section 6 — Incident Response

6.1 Company A maintains a documented Incident Response Plan (IRP), last updated
in August 2022. The plan has not been reviewed or updated in over 18 months.

6.2 No tabletop exercises or incident response drills have been conducted in the
past 24 months.

6.3 Security monitoring: Company A uses a cloud-native SIEM with log aggregation
from production systems. Alert triage is performed during business hours only
(Monday-Friday, 9am-5pm). **There is no 24/7 SOC coverage or on-call rotation
for security incidents.**

## Section 7 — Data Breach History

7.1 In November 2023, Company A experienced an unauthorized access incident.
An attacker gained access to the customer support portal through a compromised
employee credential (phishing attack). **Approximately 12,000 customer records
were accessed**, including names, email addresses, and support ticket contents.

7.2 The breach was detected 9 days after initial access. Affected customers
were notified within 30 days. No regulatory fines have been imposed to date,
though the state attorney general's office has requested additional documentation.

7.3 Post-incident remediation: MFA was subsequently enforced for the support
portal. A comprehensive post-incident review has not been completed.

## Section 8 — Third-Party Risk

8.1 Company A relies on 23 third-party vendors for critical operations, including
cloud hosting, payment processing, email delivery, and customer support tooling.

8.2 **Only 8 of 23 critical vendors (35%) have undergone a formal security
assessment.** The remaining 15 vendors have no documented security review on file.

8.3 Vendor X (payment processor) maintains PCI DSS Level 1 certification.
No other critical vendors' compliance status has been verified.

## Section 9 — Network Security

9.1 Network segmentation: Production, staging, and corporate networks are
logically segmented using VPC boundaries. **However, the development environment
has direct network access to the production database for debugging purposes.**

9.2 Firewall rules were last reviewed in March 2023. The review identified
12 overly permissive rules that have not been remediated.

9.3 Intrusion detection: Network IDS is deployed at the VPC boundary.
No host-based intrusion detection is implemented on application servers.

## Section 10 — Recommendations

1. Renew SOC 2 Type II certification (Critical)
2. Enforce MFA for all employee access, not just VPN/admin (Critical)
3. Encrypt customer data at rest in the primary database (Critical)
4. Patch critical vulnerabilities within 30 days of identification (Critical)
5. Conduct annual penetration testing (High)
6. Update incident response plan and conduct tabletop exercises (High)
7. Establish 24/7 security monitoring capability (High)
8. Complete security assessments for all critical vendors (High)
9. Remove development environment access to production database (High)
10. Implement privileged access management solution (Medium)
