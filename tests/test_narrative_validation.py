"""Offline detector tests; no provider, financial fixtures or network required.

unittest keeps these tests runnable when optional project dependencies are
absent; pytest also collects them in the normal project suite.
"""

import unittest
from copy import deepcopy
from types import SimpleNamespace

from ai_service.generation.narrative_validation import (
    NarrativeCategory as Category,
)
from ai_service.generation.narrative_validation import (
    classify_narrative,
    validate_narrative,
)

ELIGIBLE = [
    "Apple's 2024 10-K discusses supply-chain risks.",
    "The risk discussion appears in Item 1A.",
    "COVID-19 affected supplier operations.",
    "Component shortages may adversely affect revenue.",
    "Apple disclosed supplier distress and component shortages as supply-chain risks.",
    "The FY2024 filing discusses supply-chain risks.",
    "The Form 10-K discusses supply-chain risks.",
    "During 2024, supplier distress could disrupt operations.",
    "The FY2023 filing discusses supply-chain risks.",
    "Apple disclosed pricing pressure, geopolitical events, and public-health disruptions.",
]
QUANTITATIVE = [
    "Revenue increased by 12%.",
    "Revenue increased by twelve percent.",
    "Assets doubled.",
    "Net income declined by half.",
    "2024 million",
    "In 2024, revenue increased by 12%.",
    "Revenue increased by 12% according to the filing.",
    "Revenue increased by 15% according to the application-owned calculation.",
    "Cash was $50 billion.",
    "Operating margin was 32%.",
    "Revenue grew three times.",
    "Assets tripled.",
    "Assets were halved.",
    "Income increased twice.",
    "Revenue rose threefold.",
    "Margin increased by fifteen basis points.",
    "Cash was fifty billion dollars.",
    "The ratio was 3:2.",
    "The range was 10–20.",
    "Revenue increased by １２％.",
    "Cash was €50.",
]
AMBIGUOUS = [
    "The identifier is ABC123.",
    "Revenue was 1.5e9.",
    "There were twelve suppliers.",
    "Revenue was the highest.",
    "Revenue increased.",
    "Risks may affect operations; revenue increased.",
    "Revenue may have increased.",
    "The 2024 figure is discussed.",
    "The FY2030 filing discusses risks.",
    "The FY2024abc filing discusses risks.",
    "The identifier is 2024.5.",
    "Revenue grew thir\u200bteen percent.",
    "There were Ⅷ suppliers.",
    "The claim contains \x00 a control character.",
]
EXTERNAL = [
    "See https://example.com/report.",
    "See HTTP://example.com/report.",
    "See //example.com/report.",
    "See [filing](https://example.com/report).",
    "See [filing](report.html).",
    "See www.example.com.",
    "See example.invalid/report.",
]


class NarrativeValidationTests(unittest.TestCase):
    def test_cross_claim_financial_change_is_ambiguous(self):
        synthesis = SimpleNamespace(
            claims=[
                SimpleNamespace(text="Revenue is discussed.", citation_ids=["e"]),
                SimpleNamespace(text="It increased.", citation_ids=["e"]),
            ]
        )
        with self.assertRaises(ValueError):
            validate_narrative(synthesis, {"e": {"fiscal_year": 2024}}, [2024])

    def test_metadata_urls_are_not_claim_urls(self):
        registry = {
            "e": {
                "fiscal_year": 2024,
                "source_url": "https://www.sec.gov/Archives/example.htm",
                "text": "Synthetic test passage, not actual filing evidence.",
            }
        }
        synthesis = SimpleNamespace(
            claims=[
                SimpleNamespace(
                    text="The FY2024 filing discusses supply-chain risks.",
                    citation_ids=["e"],
                )
            ]
        )
        before = deepcopy(registry)
        text = synthesis.claims[0].text
        validate_narrative(synthesis, registry, [2024])
        self.assertEqual(registry, before)
        self.assertEqual(synthesis.claims[0].text, text)

    def test_matching_evidence_value_does_not_authorize_prose(self):
        registry = {"e": {"fiscal_year": 2024, "value": "12", "text": "12%"}}
        synthesis = SimpleNamespace(
            claims=[
                SimpleNamespace(
                    text="Revenue increased by 12%.",
                    citation_ids=["e"],
                )
            ]
        )
        with self.assertRaisesRegex(ValueError, "numeric claims"):
            validate_narrative(synthesis, registry, [2024])

    def test_year_must_match_request_and_cited_metadata(self):
        synthesis = SimpleNamespace(
            claims=[
                SimpleNamespace(
                    text="The FY2024 filing discusses risks.",
                    citation_ids=["e"],
                )
            ]
        )
        for year, requested in [(2023, [2024]), (2024, [2023])]:
            with self.subTest(year=year, requested=requested):
                with self.assertRaises(ValueError):
                    validate_narrative(
                        synthesis, {"e": {"fiscal_year": year}}, requested
                    )

    def test_one_bad_claim_rejects_synthesis_without_mutation(self):
        synthesis = SimpleNamespace(
            claims=[
                SimpleNamespace(
                    text="Suppliers may face distress.", citation_ids=["e"]
                ),
                SimpleNamespace(text="Assets doubled.", citation_ids=["e"]),
            ]
        )
        before = [claim.text for claim in synthesis.claims]
        with self.assertRaises(ValueError):
            validate_narrative(synthesis, {"e": {"fiscal_year": 2024}}, [2024])
        self.assertEqual([claim.text for claim in synthesis.claims], before)


# Each table entry is a separate discoverable test, not a duplicated validator.
def make_case(text, expected):
    def test(self):
        self.assertEqual(classify_narrative(text, allowed_years=[2023, 2024]), expected)

    return test


for group, samples, expected in [
    ("eligible", ELIGIBLE, Category.QUALITATIVE_OR_REFERENCE),
    ("quantitative", QUANTITATIVE, Category.QUANTITATIVE),
    ("ambiguous", AMBIGUOUS, Category.AMBIGUOUS),
    ("external", EXTERNAL, Category.PROHIBITED_EXTERNAL_REFERENCE),
]:
    for index, sample in enumerate(samples):
        setattr(
            NarrativeValidationTests,
            f"test_{group}_{index:02}",
            make_case(sample, expected),
        )


if __name__ == "__main__":
    unittest.main()
