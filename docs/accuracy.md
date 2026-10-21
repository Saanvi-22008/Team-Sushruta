# Accuracy and safety notes — Phase 1

Sushruta is a proof of concept, not a medical device. It does not diagnose a wound or replace a clinician. The app currently displays only simulated readings.

The deterministic safety rules and API validation have automated tests. Those tests show that the configured code paths behave as written; they do not establish clinical accuracy. Every clinical threshold in `config/clinical_thresholds.json` is a placeholder and must be reviewed by a clinician and the hardware team before any real-world use.

There is no live patch connection in this phase. No real sensor, patient history, or clinical outcome has been validated.
