"""Tests of the party import parser (no Django needed): python -m unittest billing.test_importer"""
import io
import unittest

from .importer import ImportFileError, MAX_ROWS, build_parties, read_csv_text, read_table

STATES = {"West Bengal": "19", "Maharashtra": "27", "Delhi": "07"}
GOOD_GSTIN = "19AABAB6861E1ZS"


def parse(text):
    return build_parties(read_csv_text(text), STATES)[0]


class ParserTests(unittest.TestCase):
    def test_plain_csv(self):
        p = parse(f'name,address,gstin,state,phone,email\n"Alpha, Traders","1 Park St, Kolkata",{GOOD_GSTIN},West Bengal,9830000000,a@b.com\n')[0]
        self.assertEqual((p["name"], p["address"], p["gstin"], p["state"], p["phone"], p["email"]),
                         ("Alpha, Traders", "1 Park St, Kolkata", GOOD_GSTIN, "West Bengal", "9830000000", "a@b.com"))
        self.assertEqual((p["row"], p["error"], p["warnings"]), (2, "", []))

    def test_other_separators_and_headings(self):
        for sep in (";", "\t", "|"):
            rows = parse(f"Party Name{sep}Mobile No{sep}GST No\nAlpha{sep}98300{sep}\n")
            self.assertEqual((rows[0]["name"], rows[0]["phone"]), ("Alpha", "98300"), repr(sep))

    def test_a_title_row_above_the_headings_is_skipped(self):
        rows = parse("Customer list 2026\n\nName,Phone\nAlpha,1\n")
        self.assertEqual((rows[0]["name"], rows[0]["row"]), ("Alpha", 4))

    def test_blank_rows_ignored_and_names_cleaned(self):
        rows = parse("name\n\n   Alpha    Traders  \n,\n")
        self.assertEqual([r["name"] for r in rows], ["Alpha Traders"])

    def test_missing_name_and_duplicate_name_are_errors(self):
        rows = parse("name,phone\nAlpha,1\n,2\nALPHA,3\n")
        self.assertEqual([r["error"] for r in rows], ["", "no party name", "same name as row 2 of this file"])

    def test_state_by_name_code_and_gstin(self):
        rows = parse(f"name,state,gstin\nA,maharashtra,\nB,07,\nC,,{GOOD_GSTIN}\nD,Gujarat,\nE,Gujarat,{GOOD_GSTIN}\n")
        self.assertEqual([r["state"] for r in rows], ["Maharashtra", "Delhi", "West Bengal", "", "West Bengal"])
        self.assertEqual(rows[3]["warnings"], ['state "Gujarat" is not recognised (left blank)'])
        self.assertIn("taken from the GSTIN", rows[4]["warnings"][0])

    def test_gstin_is_cleaned_and_checked_but_never_blocks(self):
        rows = parse(f"name,gstin\nA,19 aabab6861e1zs\nB,19AABAB6861E1ZX\nC,123\n")
        self.assertEqual(rows[0]["gstin"], GOOD_GSTIN)
        self.assertEqual(rows[0]["warnings"], [])
        self.assertEqual([r["warnings"] for r in rows[1:]], [["GSTIN looks invalid (saved as typed)"]] * 2)
        self.assertEqual([r["error"] for r in rows], ["", "", ""])

    def test_bad_email_is_dropped_with_a_warning(self):
        r = parse("name,email\nA,not-an-email\nB,ok@x.com\n")
        self.assertEqual((r[0]["email"], r[1]["email"]), ("", "ok@x.com"))
        self.assertEqual(len(r[0]["warnings"]), 1)

    def test_long_phone_is_shortened(self):
        r = parse("name,phone\nA," + "9" * 50 + "\n")[0]
        self.assertEqual((len(r["phone"]), len(r["warnings"])), (40, 1))

    def test_no_name_column_and_empty_file(self):
        with self.assertRaises(ImportFileError):
            build_parties(read_csv_text("address,phone\nx,1\n"), STATES)
        with self.assertRaises(ImportFileError):
            build_parties([], STATES)
        with self.assertRaises(ImportFileError):
            build_parties(read_csv_text("name,phone\n"), STATES)

    def test_too_many_rows(self):
        with self.assertRaises(ImportFileError):
            build_parties(read_csv_text("name\n" + "\n".join(f"P{i}" for i in range(MAX_ROWS + 1))), STATES)


class FileTests(unittest.TestCase):
    def test_utf8_with_bom_and_windows_encoding(self):
        data = "﻿name,address\nCafé Corner,x\n".encode("utf-8")
        self.assertEqual(build_parties(read_table("a.csv", data), STATES)[0][0]["name"], "Café Corner")
        data = "name,address\nCafé Corner,x\n".encode("cp1252")
        self.assertEqual(build_parties(read_table("a.csv", data), STATES)[0][0]["name"], "Café Corner")

    def test_xlsx(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Party Name", "GST No", "Mobile", "State"])
        ws.append(["Alpha", GOOD_GSTIN, 9830000000, "West Bengal"])  # a phone number stored as a number
        ws.append([None, None, None, None])
        ws.append(["Beta", None, 98.0, 27])                          # state typed as a code number
        buf = io.BytesIO()
        wb.save(buf)
        rows = build_parties(read_table("parties.xlsx", buf.getvalue()), STATES)[0]
        self.assertEqual([(r["name"], r["phone"], r["state"]) for r in rows], [("Alpha", "9830000000", "West Bengal"), ("Beta", "98", "Maharashtra")])

    def test_bad_files(self):
        with self.assertRaises(ImportFileError):
            read_table("old.xls", b"x")
        with self.assertRaises(ImportFileError):
            read_table("broken.xlsx", b"this is not a zip file")
        with self.assertRaises(ImportFileError):
            read_table("big.csv", b"a" * (3 * 1024 * 1024 + 1))


if __name__ == "__main__":
    unittest.main()
