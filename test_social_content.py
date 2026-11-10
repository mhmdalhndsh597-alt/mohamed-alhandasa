import unittest
from decimal import Decimal

from social_content import build_drafts, facebook_graph_payload, telegram_payload


class SocialContentTests(unittest.TestCase):
    def test_builds_three_platform_drafts(self):
        drafts = build_drafts(chain_id=1, block=123, volume="42.5", tx_count=8,
                              whale_count=2, largest_whale=Decimal("1000"), spike_percent=Decimal("75"))
        self.assertEqual([draft.platform for draft in drafts], ["facebook", "x", "instagram"])
        self.assertIn("#WhaleAlert", drafts[1].text)
        self.assertIn("لا يتم توقيع", drafts[0].text)
        self.assertLessEqual(len(drafts[1].text), 280)

    def test_api_templates_do_not_contain_tokens(self):
        facebook = facebook_graph_payload(page_id="page-1", message="draft")
        telegram = telegram_payload(chat_id="chat-1", message="draft")
        self.assertNotIn("access_token", str(facebook["json"]))
        self.assertEqual(facebook["token_env"], "FACEBOOK_PAGE_ACCESS_TOKEN")
        self.assertNotIn("bot-token-value", str(telegram))
        self.assertEqual(telegram["token_env"], "TELEGRAM_BOT_TOKEN")


if __name__ == "__main__":
    unittest.main()
