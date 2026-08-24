# Input Tax Credit (ITC) Rules & Rule 88A Optimization Guide

This reference details the legal and mathematical rules governing ITC eligibility, statutory reversals, and optimal set-off under the Indian CGST / IGST Acts.

---

## 1. Statutory Conditions for Claiming ITC (Section 16)

Under Section 16(2) of the CGST Act, a registered taxpayer is entitled to credit of input tax only if **all 4 conditions** are simultaneously satisfied:
1. **Possession of Tax Invoice / Debit Note:** The taxpayer has a valid tax invoice or debit note issued by a registered supplier.
2. **Receipt of Goods or Services:** The goods or services have been received (or deemed received under bill-to-ship-to models).
3. **Tax Actually Paid to Government (Section 16(2)(c)):** The supplier has paid the tax to the government (either in cash or via eligible ITC) and filed their return. Reflected in **GSTR-2B**.
4. **Filing of Return (Section 16(2)(d)):** The taxpayer has furnished their return under Section 39 in Form GSTR-3B.

### Time Limit for Claiming ITC (Section 16(4))
ITC for any invoice/debit note pertaining to a financial year must be claimed on or before:
- **30th November** of the following financial year, or
- The actual date of furnishing the Annual Return (Form GSTR-9), whichever is earlier.

---

## 2. Blocked Credits (Section 17(5)) $\to$ Table 4(B)(1) Permanent Reversal

Input tax credit is **explicitly blocked** and cannot be claimed on:
1. **Motor Vehicles (17(5)(a)):** Motor vehicles for transportation of persons having approved seating capacity of $\le 13$ persons (including driver), except when used for making taxable supply of further vehicles, passenger transportation, or driving school training.
2. **Food, Beverages & Catering (17(5)(b)(i)):** Food and beverages, outdoor catering, beauty treatment, health services, cosmetic and plastic surgery.
3. **Club / Fitness Memberships (17(5)(b)(ii)):** Membership of a club, health, and fitness centre.
4. **Travel Benefits (17(5)(b)(iii)):** Travel benefits extended to employees on vacation (LTA, home travel).
5. **Works Contract for Immovable Property (17(5)(c)):** Works contract services for construction of an immovable property (other than plant and machinery), except where it is an input service for further supply of works contract.
6. **Self-Construction (17(5)(d)):** Goods or services received for construction of an immovable property on own account (other than plant and machinery).
7. **Lost, Stolen, Destroyed, or Written Off Goods (17(5)(h)):** Goods lost, stolen, destroyed, written off, or disposed of by way of gift or free samples.
8. **Personal Consumption (17(5)(g)):** Goods or services used for personal consumption.

---

## 3. Temporary Reversals & Reclaims

### Rule 37: Reversal for Failure to Pay Consideration within 180 Days
- Under the second proviso to Section 16(2), if a buyer fails to pay the supplier the amount towards the invoice value plus tax within **180 days** from the invoice date:
  - The amount of ITC claimed must be reversed in **Table 4(B)(2)** in the month following the 180 days.
  - Taxpayer is liable to pay interest under Section 50 @ 18% p.a. from the date of claiming the ITC until the date of reversal.
- **Reclaim (Table 4(D)(1)):** Once the buyer pays the supplier, the reversed ITC can be **100% reclaimed** in Table 4(A)(5) and reported in Table 4(D)(1), with no time limit!

### Rule 37A: Reversal on Supplier Default in Filing GSTR-3B
- If a supplier furnishes an invoice in GSTR-1 (so it appears in GSTR-2B) but fails to file their GSTR-3B by the 30th September/November following the end of the financial year:
  - The recipient must reverse the ITC in **Table 4(B)(2)** on or before 30th November.
  - Can be reclaimed in Table 4(A)(5) and Table 4(D)(1) when the supplier subsequently files their GSTR-3B.

---

## 4. Rule 88A & Section 49 Optimization Algorithm

### The Statutory Order of Utilization
Rule 88A of the CGST Rules prescribes the following strict order of utilization:

```
[1. IGST Credit] ---> MUST exhaust 100% against IGST Liability
                ---> Remaining IGST Credit MUST be utilized for CGST and SGST in ANY PROPORTION
                ---> (Only after IGST Credit is completely ₹0, proceed to CGST/SGST credits)

[2. CGST Credit] ---> Utilized for remaining CGST Liability
                ---> Remaining CGST Credit utilized for remaining IGST Liability
                ---> (NEVER utilized for SGST)

[3. SGST Credit] ---> Utilized for remaining SGST Liability
                ---> Remaining SGST Credit utilized for remaining IGST Liability
                ---> (NEVER utilized for CGST)

[4. Cess Credit] ---> Utilized ONLY for Cess Liability

[5. RCM Liability] ---> Section 49(4): Inward RCM Liability MUST be paid 100% IN CASH!
```

### Linear Optimization Strategy in `itc_optimizer.py`
To minimize immediate cash outflow:
1. Calculate the credit shortfall in CGST: $\text{Shortfall}_{\text{CGST}} = \max(0, \text{Liability}_{\text{CGST}} - \text{Credit}_{\text{CGST}})$.
2. Calculate the credit shortfall in SGST: $\text{Shortfall}_{\text{SGST}} = \max(0, \text{Liability}_{\text{SGST}} - \text{Credit}_{\text{SGST}})$.
3. Allocate remaining IGST credit first to cover whichever shortfall is higher, thereby preventing asymmetric cash demands while the other ledger has stranded credit.
