# GSTR-1 Field-by-Field Statutory Reference Guide

This reference explains every table, schedule, and field of **Form GSTR-1** (Statement of Outward Supplies of Goods and Services) as per Section 37 of the CGST Act 2017 and Rule 59 of the CGST Rules 2017.

---

## 1. Table 4: Taxable Outward Supplies to Registered Persons (B2B)

- **Scope:** All supplies made to buyers who hold an active GSTIN.
- **Sub-Tables:**
  - **4A:** Regular B2B supplies (intra-state and inter-state).
  - **4B:** Supplies attracting Reverse Charge under Section 9(3) / 5(3) (`rchrg = "Y"`).
  - **4C:** Supplies made through E-Commerce Operators under Section 9(5).
  - **6B:** Supplies made to SEZ units or developers with payment of tax (`inv_typ = "SEZWP"`).
  - **6C:** Deemed exports (`inv_typ = "DE"`).
- **Mandatory Fields:**
  - `ctin`: Recipient GSTIN (15 characters, valid checksum).
  - `inum`: Invoice Number (max 16 characters, alphanumeric, unique per financial year).
  - `idt`: Invoice Date (DD-MM-YYYY).
  - `val`: Total invoice value (Taxable Value + Taxes).
  - `pos`: 2-digit Place of Supply state code.
  - `itms`: Line-item breakdown with `txval`, `rt`, `iamt`, `camt`, `samt`, `csamt`.

---

## 2. Table 5: Taxable Outward Inter-State Supplies to Unregistered Persons (B2CL)

- **Statutory Change (Notification No. 12/2024–Central Tax, effective August 1, 2024):**
  - The threshold for B2CL invoice-wise reporting was **reduced from ₹2,50,000 to ₹1,00,000**.
- **Scope:** Inter-state supplies made to unregistered buyers (or consumers) where the invoice value **exceeds ₹1,00,000**.
- **Reporting:** Invoice-wise details grouped by Place of Supply (POS).

---

## 3. Table 6: Zero-Rated Supplies and Deemed Exports

- **Table 6A (Exports):**
  - `EXPWP`: Export with payment of Integrated Tax.
  - `EXPWOP`: Export without payment of tax under Letter of Undertaking (LUT) / Bond.
  - Required Fields: Port Code (6 digits), Shipping Bill Number, Shipping Bill Date.
- **Table 6B (SEZ):** Supplies to SEZ units / developers.
- **Table 6C (Deemed Exports):** Supplies notified under Section 147.

---

## 4. Table 7: Taxable Supplies to Unregistered Persons (B2CS)

- **Scope:**
  - All **intra-state** supplies to unregistered persons (regardless of invoice value).
  - **Inter-state** supplies to unregistered persons where the invoice value is **₹1,00,000 or less**.
- **Reporting:** Consolidated net taxable value grouped by:
  1. Supply Type (`INTRA` / `INTER`)
  2. Place of Supply (`pos`)
  3. Applicable GST Rate (`rt`)
  4. E-Commerce Operator GSTIN (`etin`, if applicable)

---

## 5. Table 8: Nil-Rated, Exempted, and Non-GST Outward Supplies

- **Categories:**
  - **Nil-Rated:** Goods/services attracting 0% GST (e.g. fresh unprocessed milk, salt).
  - **Exempted:** Supplies exempt under Section 11 / Section 6 of IGST Act (e.g. healthcare, basic education).
  - **Non-GST:** Supplies outside the scope of GST under Section 9(2) or Schedule III (e.g. petrol, diesel, alcohol for human consumption).
- **Sub-Classifications:**
  - Inter-state supplies to registered persons.
  - Inter-state supplies to unregistered persons.
  - Intra-state supplies to registered persons.
  - Intra-state supplies to unregistered persons.

---

## 6. Table 9: Credit / Debit Notes and Amendments

- **Table 9B (CDNR):** Credit and Debit Notes issued to registered persons against original invoices.
- **Table 9B (CDNUR):** Credit and Debit Notes issued for B2CL inter-state unregistered supplies and exports.
- **Note Types:**
  - `C`: Credit Note (reduces outward tax liability).
  - `D`: Debit Note (increases outward tax liability).

---

## 7. Table 11: Advances Received and Adjusted

- **Table 11A:** Advance amount received in the current tax period for services where invoice has not yet been issued (tax must be paid on receipt basis for services).
- **Table 11B:** Advance amount received in earlier periods adjusted against invoices issued in the current period.

---

## 8. Table 12: HSN-Wise Summary of Outward Supplies

- **Mandatory Reporting (May 2025+ Advisory):**
  - Must be bifurcated into **Table 12A (B2B Supplies)** and **Table 12B (B2C Supplies)**.
- **Digit Rules:**
  - Aggregate Annual Turnover (AATO) $\le ₹5\text{ Crore}$: Minimum **4 digits** of HSN/SAC.
  - AATO $> ₹5\text{ Crore}$: Minimum **6 digits** of HSN/SAC (8 digits for exports/chemicals).
- **Required Fields:** HSN/SAC code, Description, Unit Quantity Code (UQC), Total Quantity, Total Value, Taxable Value, IGST, CGST, SGST, Cess.

---

## 9. Table 13: Documents Issued During the Tax Period

- **Document Categories (1 to 12):**
  1. Invoices for outward supply
  2. Invoices for inward supply from unregistered person (RCM)
  3. Revised Invoice
  4. Debit Note
  5. Credit Note
  6. Receipt voucher
  7. Payment Voucher
  8. Refund voucher
  9. Delivery Challan for job work
  10. Delivery Challan for supply on approval
  11. Delivery Challan in case of liquid gas
  12. Other Delivery Challans
- **Fields:** From Serial No., To Serial No., Total Number, Cancelled, Net Issued.
