"""Intro card content - three slides shown on first launch.

Each entry is a dict with:
  title    : short headline
  body     : 2-3 sentence explanation (plain text, no markdown)
  icon     : card-level icon filename (from mockup/icon/)
  features : list of {icon, title, desc} shown as feature rows (slide 3 only)
  caption  : one-line takeaway shown at the bottom of the card
  subcaption : secondary caption line
"""

from .. import content as content_mod

SLIDES = [
    {
        "title": content_mod.get_text_content("onboard_slide1_title"),
        "body": content_mod.get_text_content("onboard_slide1_body"),
        "png":"page1.png",
        "icon":"icon-model-warning.png",
        "caption": content_mod.get_text_content("onboard_slide1_caption"),
        "subcaption": content_mod.get_text_content("onboard_slide1_subcaption"),
    },
    {
        "title": content_mod.get_text_content("onboard_slide2_title"),
        "body": content_mod.get_text_content("onboard_slide2_body"),
        "png":"page2.png",
        "icon":"icon-attention.png",
        "caption": content_mod.get_text_content("onboard_slide2_caption"),
        "subcaption": content_mod.get_text_content("onboard_slide2_subcaption"),
    },
    {
        "title": content_mod.get_text_content("onboard_slide3_title"),
        "body": content_mod.get_text_content("onboard_slide3_body"),
        "features": [
            {
                "icon": "icon-robustness.png",
                "title": "Systematic Adversarial Testing",
                "desc": content_mod.get_text_content("onboard_slide3_feature_testing_desc"),
            },
            {
                "icon": "icon-report.png",
                "title": "Clear, Actionable Reports",
                "desc": content_mod.get_text_content("onboard_slide3_feature_reports_desc"),
            },
            {
                "icon": "icon-adversarial-target.png",
                "title": "Stronger, Safer Models",
                "desc": content_mod.get_text_content("onboard_slide3_feature_models_desc"),
            },
        ],
        "icon": "icon-test-pass.png",
        "caption": content_mod.get_text_content("onboard_slide3_caption"),
        "subcaption": content_mod.get_text_content("onboard_slide3_subcaption"),
    },
]
