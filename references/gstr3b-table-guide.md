# GSTR-3B Field-by-Field Statutory Reference Guide

This reference explains every table and field of **Form GSTR-3B** (Summary Return and Tax Payment) as per Section 39 of the CGST Act 2017 and Rule 61 of the CGST Rules 2017.

---

## 1. Table 3.1: Details of Outward Supplies and Inward Supplies Liable to Reverse Charge

| Table Key | Description | Taxable Turnover | IGST | CGST | SGST | Cess | Notes |
|---|---|---|---|---|---|---|---|
| **3.1(a)** | Outward taxable supplies (other than zero rated, nil rated and exempted) | Yes | Yes | Yes | Yes | Yes | Derived from GSTR-1 Tables 4, 5, 7, 9, 11 |
| **3.1(b)** | Outward taxable supplies (zero rated) | Yes | Yes | - | - | Yes | From GSTR-1 Table 6A (Exports with payment) & 6B |
| **3.1(c)** | Other outward supplies (Nil rated, exempted) | Yes | - | - | - | - | From GSTR-1 Table 8 |
| **3.1(d)** | Inward supplies (liable to reverse charge) | Yes | Yes | Yes | Yes | Yes | **MUST be paid 100% in CASH** u/s 49(4) |
| **3.1(e)** | Non-GST outward supplies | Yes | - | - | - | - | From GSTR-1 Table 8 (Petroleum, alcohol, etc.) |

---

## 2. Table 3.1.1: Supplies Notified under Section 9(5) of the CGST Act

- **3.1.1(i):** Taxable supplies on which E-Commerce Operator (ECO) pays tax under Section 9(5) (e.g. Uber/Ola passenger transport, Swiggy/Zomato restaurant services).
  - Reported by the ECO who pays the tax.
- **3.1.1(ii):** Taxable supplies made by the registered person through ECO on which ECO is liable to pay tax.
  - Reported by the merchant/restaurant (reported as turnover only; tax is paid by ECO).

---

## 3. Table 3.2: Details of Inter-State Supplies Made to Unregistered Persons, Composition Dealers, and UIN Holders

- **Purpose:** Sub-breakdown of inter-state supplies already included in Table 3.1(a) by Place of Supply (POS) to allow proper revenue transfer to destination States under the IGST Act.
- **Bifurcation:**
  - Supplies made to Unregistered Persons (from B2CL and B2CS Inter-state).
  - Supplies made to Composition Taxable Persons.
  - Supplies made to UIN Holders (embassies, UN bodies).

---

## 4. Table 4: Eligible Input Tax Credit (ITC)

### 4(A) ITC Available (whether in full or part)
- **4(A)(1): Import of Goods:** Sourced from ICEGATE / Bill of Entry records in GSTR-2B (`impg` / `impgsez`).
- **4(A)(2): Import of Services:** Sourced from self-invoices for overseas services.
- **4(A)(3): Inward supplies liable to reverse charge:** Sourced from self-invoices where RCM tax was paid.
- **4(A)(4): Inward supplies from ISD:** Sourced from Input Service Distributor filings in GSTR-2B (`isd`).
- **4(A)(5): All Other ITC:** Auto-drafted from regular domestic purchases in GSTR-2B (`b2b`, `b2ba`, `cdnr`).

### 4(B) ITC Reversed
- **4(B)(1) As per rules 38, 42 and 43 and section 17(5):**
  - **Permanent Reversals:** Blocked credits under Section 17(5) (motor vehicles, food/catering, health club, personal use) and proportional reversals for exempt supplies under Rule 42 (inputs) and Rule 43 (capital goods).
- **4(B)(2) Others:**
  - **Temporary Reversals:** Rule 37 (invoices unpaid for > 180 days from invoice date), Rule 37A (supplier default in filing 3B), goods not yet received.

### 4(C) Net ITC Available
$$\text{Table 4(C)} = \text{Table 4(A)} - \text{Table 4(B)}$$
Computed component-wise for Integrated Tax, Central Tax, State/UT Tax, and Cess.

### 4(D) Other Details
- **4(D)(1) ITC Reclaimed:** Amount reclaimed which was reversed under Table 4(B)(2) in earlier periods upon payment to vendor.
- **4(D)(2) Ineligible ITC:** Section 16(4) time-barred credit and ITC restricted due to POS rules (reflected in GSTR-2B with `itcavl = "N"`).

---

## 5. Table 5: Values of Exempt, Nil-Rated, and Non-GST Inward Supplies

- Inward supplies received from suppliers under composition scheme, exempt and nil-rated supply (Inter-state vs Intra-state).
- Non-GST inward supplies.

---

## 6. Table 5.1 & 5.1.1: Interest and Late Fee Payable

- **Interest u/s 50:** 18% p.a. calculated per day on net cash liability paid after the due date.
- **Late Fee u/s 47:** Calculated per day of delay, subject to statutory turnover caps.

---

## 7. Table 6.1: Payment of Tax (Electronic Credit / Cash Ledger Offset)

- Implements **Rule 88A / Section 49, 49A, 49B** set-off order.
- Generates the exact amount required to be deposited in the Electronic Cash Ledger via **Challan PMT-06** before clicking the "Offset Liability" button.
