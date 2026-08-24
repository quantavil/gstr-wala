# Step-by-Step GST Portal Filing Walkthrough

This reference walks through the complete procedure for filing **Form GSTR-1** and **Form GSTR-3B** on the official GST Portal (`www.gst.gov.in`).

---

## Phase 1: Filing GSTR-1 (Outward Supplies)

### Route A: Offline JSON Upload (Recommended & Fastest)
1. **Login:** Log in to `www.gst.gov.in` using your credentials and OTP.
2. **Navigate:** Go to **Services > Returns > Returns Dashboard**.
3. **Select Period:** Select the Financial Year (e.g. `2026-27`) and Return Filing Period (e.g. `April`).
4. **Choose Offline Mode:** Click on the **Prepare Offline** button under the GSTR-1 tile.
5. **Upload JSON:** In the "Upload" tab, choose the generated `GSTR1_portal.json` file from your workspace `output/` directory and upload it.
6. **Processing:** Wait 1-2 minutes for the portal to process the JSON. Refresh to ensure status says `Processed` with 0 errors.
7. **View Summary:** Return to the Dashboard and click **Prepare Online** under GSTR-1.
8. **Reconcile with Filing Pack:** Verify that the summary tile totals match the `output/gstr1-filing-pack.md` **to the rupee**.
9. **Generate Summary & Submit:** Click **Generate Summary**, review the preview PDF, check the declaration box, and click **Proceed to File / File Return**.
10. **EVC Verification:** Select Authorized Signatory, click **File with EVC**, enter the OTP received on the registered mobile/email, and record the **ARN (Acknowledgement Reference Number)**.

---

## Phase 2: Filing GSTR-3B (Summary & Tax Payment)

### Step 1: Verification of Auto-Drafted Values
1. On the **Returns Dashboard**, select the tax period and click **Prepare Online** under the GSTR-3B tile.
2. Verify that **Table 3.1** (Outward Supplies) has auto-populated from your filed GSTR-1.
3. Verify that **Table 4** (Eligible ITC) aligns with your `output/reconciliation-report.md`. If manual edits are made to Table 4(B) reversals, verify that Net ITC in Table 4(C) matches the computation.

### Step 2: Payment of Tax & Challan Generation (Table 6.1)
1. Click **Save GSTR-3B** and then **Proceed to Payment**.
2. Review the **Payment of Tax Table (6.1)**:
   - The portal will automatically apply Rule 88A set-off based on available Credit Ledger balances.
   - Verify that the **Cash Required** matches `output/gstr3b-filing-pack.md`.
3. **Create Challan (PMT-06):**
   - If Electronic Cash Ledger balance is insufficient, click **Create Challan**.
   - The portal will auto-fill the exact shortfall in each tax head (IGST, CGST, SGST, Cess).
   - Select Payment Mode (Net Banking / NEFT / RTGS / UPI / Over the Counter) and complete payment.
4. **Offset Liability:**
   - Once cash reflects in the Cash Ledger, return to Table 6.1 and click **Make Payment / Post Credit to Ledger (Offset Liability)**.
   - Confirm the debit prompt. Status will update to `Offset Success`.

### Step 3: Final Submission & e-Verification
1. Check the declaration checkbox, select the Authorized Signatory from the dropdown.
2. Click **File GSTR-3B with EVC** (or DSC for companies).
3. Enter the OTP and receive the final filing confirmation with **ARN**.
4. Download the filed return PDF and save the ARN in `work/progress.md`.
