"""Fixture tests for dedup_independent.py. Run: python -m unittest test_dedup_independent -v"""

import unittest
from pathlib import Path

import pandas as pd

import dedup_independent as d


def frame(rows):
    base = {c: None for c in d.FROZEN_SCHEMA}
    out = []
    for k, r in enumerate(rows):
        row = dict(base, article_id=f"a{k}", publisher_id=r.get("pub", "p"), url=f"https://x/{k}", **{
            k2: v for k2, v in r.items() if k2 != "pub"})
        out.append(row)
    return pd.DataFrame(out, columns=d.FROZEN_SCHEMA)


LEDE = "Bộ Tư lệnh TPHCM cho biết đội quy tập vừa tìm được thêm hài cốt liệt sĩ tại rãnh mộ thứ hai ở công viên"


class DedupTests(unittest.TestCase):
    def test_normalize_unescapes_html_and_keeps_diacritics(self):
        self.assertEqual(d.normalize("Biển người &apos;đi bão&apos; <b>TPHCM</b>!"), "biển người đi bão tphcm")

    def test_canonical_url_tracking_variants_are_exact_duplicates(self):
        df = frame([
            {"title": "Different title A", "description": "different description A",
             "canonical_url": "HTTPS://WWW.Example.com/news/item/?utm_source=feed&gclid=abc#top"},
            {"title": "Different title B", "description": "different description B",
             "canonical_url": "https://example.com/news/item"},
        ])
        r = d.analyze(df)
        self.assertEqual(r["accepted"][(0, 1)][0], "EXACT_DUPLICATE")
        self.assertEqual(r["accepted"][(0, 1)][2], "identical_normalized_canonical_url")

    def test_exact_title_and_description_detected_including_empty_descriptions(self):
        df = frame([
            {"title": "Same Title", "description": "One two three four five six seven"},
            {"title": "same  title!", "description": "One two three four five six seven."},
            {"title": "Only title", "description": None},
            {"title": "Only Title", "description": ""},
        ])
        r = d.analyze(df)
        self.assertEqual({k: v[0] for k, v in r["accepted"].items()}, {(0, 1): "EXACT_DUPLICATE", (2, 3): "EXACT_DUPLICATE"})
        self.assertEqual(len(r["families"]), 2)

    def test_verbatim_lede_with_new_headline_is_syndicated(self):
        df = frame([
            {"title": "Đêm không ngủ mừng chiến thắng", "description": LEDE},
            {"title": "Biển người xuyên đêm ăn mừng", "description": LEDE},
        ])
        r = d.analyze(df)
        self.assertEqual(r["accepted"][(0, 1)][0], "SYNDICATED_COPY")

    def test_same_headline_different_lede_is_not_a_copy(self):
        df = frame([
            {"title": "Chưa thí điểm thi tốt nghiệp trên máy tính năm 2027", "description": "Phó thủ tướng chỉ đạo chưa tổ chức thí điểm thi trên máy tính đối với kỳ thi năm 2027 như Bộ đề xuất"},
            {"title": "Chưa thí điểm thi tốt nghiệp trên máy tính năm 2027", "description": "Yêu cầu trước mắt chưa thí điểm; Bộ Giáo dục sẽ rà soát phương án tổ chức thi an toàn hơn cho học sinh cả nước"},
        ])
        r = d.analyze(df)
        self.assertNotIn((0, 1), r["accepted"])
        self.assertEqual(r["pair_info"][(0, 1)][0], "SAME_EVENT_INDEPENDENT")

    def test_numeric_conflict_vetoes_copy(self):
        a = "Cựu Trưởng Công an Phú Quốc bị tuyên phạt 18 năm tù về tội lừa đảo chiếm đoạt tài sản tại tỉnh An Giang"
        b = "Cựu Trưởng Công an Phú Quốc bị đề nghị phạt 14 16 năm tù về tội lừa đảo chiếm đoạt tài sản tại tỉnh An Giang"
        df = frame([{"title": "t1", "description": a}, {"title": "t2", "description": b}])
        r = d.analyze(df)
        self.assertNotIn((0, 1), r["accepted"])
        self.assertIn("numeric details conflict", r["pair_info"][(0, 1)][2])

    def test_published_more_than_a_week_apart_vetoes_copy(self):
        df = frame([
            {"title": "a a", "description": LEDE, "published_at": "2026-09-01T00:00:00Z"},
            {"title": "b b", "description": LEDE, "published_at": "2026-09-20T00:00:00Z"},
        ])
        self.assertNotIn((0, 1), d.analyze(df)["accepted"])

    def test_exact_match_overrides_more_than_a_week_gap(self):
        df = frame([
            {"title": "Same exact story", "description": LEDE, "published_at": "2026-09-01T00:00:00Z"},
            {"title": "same exact story", "description": LEDE, "published_at": "2026-09-20T00:00:00Z"},
        ])
        self.assertEqual(d.analyze(df)["accepted"][(0, 1)][0], "EXACT_DUPLICATE")

    def test_missing_description_never_creates_a_copy(self):
        df = frame([{"title": "Cùng một tiêu đề dài khá đặc biệt", "description": None},
                    {"title": "Cùng một tiêu đề dài khá đặc biệt hôm nay", "description": LEDE}])
        self.assertEqual(d.analyze(df)["accepted"], {})

    def test_same_event_label_never_assigns_a_family(self):
        df = frame([
            {"title": "Chưa thí điểm thi tốt nghiệp trên máy tính năm 2027", "description": "Phó thủ tướng chỉ đạo chưa tổ chức thí điểm thi trên máy tính đối với kỳ thi năm 2027 như Bộ đề xuất"},
            {"title": "Chưa thí điểm thi tốt nghiệp trên máy tính năm 2027", "description": "Yêu cầu trước mắt chưa thí điểm; Bộ Giáo dục sẽ rà soát phương án tổ chức thi an toàn hơn cho học sinh cả nước"},
        ])
        r = d.analyze(df)
        self.assertEqual(r["pair_info"][(0, 1)][0], "SAME_EVENT_INDEPENDENT")
        self.assertEqual(r["assignment"], [None, None])

    def test_family_id_deterministic_and_order_independent(self):
        rows = [
            {"title": "x1", "description": LEDE},
            {"title": "x2", "description": LEDE},
            {"title": "unrelated thing", "description": "một câu hoàn toàn khác biệt về chủ đề bóng đá quốc tế cuối tuần này"},
        ]
        df = frame(rows)
        f1 = d.analyze(df)["assignment"]
        self.assertEqual(f1, d.analyze(df)["assignment"])
        self.assertIsNone(f1[2])
        swapped = df.iloc[[1, 0, 2]].reset_index(drop=True)
        f2 = d.analyze(swapped)["assignment"]
        self.assertEqual(f1[0], f2[0])  # same members -> same family id regardless of row order

    def test_schema_violation_fails(self):
        import tempfile, os
        p = os.path.join(tempfile.mkdtemp(), "bad.parquet")
        pd.DataFrame({"title": ["x"]}).to_parquet(p)
        with self.assertRaises(SystemExit):
            d.load_master(__import__("pathlib").Path(p))

    def test_output_preserves_rows_schema_and_all_other_columns(self):
        df = frame([
            {"title": "x1", "description": LEDE},
            {"title": "x2", "description": LEDE},
            {"title": "independent", "description": "nội dung riêng không trùng với bài còn lại trong dữ liệu"},
        ])
        result = d.analyze(df)
        out = d.annotated_output(df, result["assignment"])
        other = [c for c in d.FROZEN_SCHEMA if c != "duplicate_family_id"]
        self.assertEqual(len(out), len(df))
        self.assertEqual(list(out.columns), d.FROZEN_SCHEMA)
        self.assertTrue(out[other].equals(df[other]))

    def test_frozen_1223_row_snapshot_output_contract(self):
        repo = Path(__file__).resolve().parents[5]
        df = d.load_master(repo / "data/processed/master/articles_master.parquet")
        self.assertEqual(len(df), 1223)
        out = d.annotated_output(df, d.analyze(df)["assignment"])
        other = [c for c in d.FROZEN_SCHEMA if c != "duplicate_family_id"]
        self.assertEqual(len(out), 1223)
        self.assertEqual(list(out.columns), d.FROZEN_SCHEMA)
        self.assertTrue(out[other].equals(df[other]))
        self.assertTrue(out["article_id"].is_unique)


if __name__ == "__main__":
    unittest.main()
