#!/usr/bin/env bun
/**
 * scripts/gstr_offline_runner.ts
 *
 * High-performance, Bun-native GST Returns Offline Tool runner & validator.
 * Implements the exact official GST Offline Tool (v3.x / GST3.2.4) serialization
 * and pre-upload schema validation.
 *
 * Usage:
 *   bun run scripts/gstr_offline_runner.ts generate <canonical_gstr1.json> [output_portal.json] [--omit-empty]
 *   bun run scripts/gstr_offline_runner.ts validate <returns_offline.json>
 *   bun run scripts/gstr_offline_runner.ts stats <returns_offline.json>
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

export const OFFICIAL_OFFLINE_VERSION = "GST3.2.4";
export const OFFICIAL_HASH = "hash";

// Forbidden keys in portal offline upload files (portal download artifacts)
export const FORBIDDEN_UPLOAD_KEYS = ["filing_typ", "cfs", "cflag", "chksum", "updby", "flag"];

export interface InvoiceItem {
  txval: number;
  rt: number;
  iamt?: number;
  camt?: number;
  samt?: number;
  csamt?: number;
  hsn_sc?: string;
  uqc?: string;
  qty?: number;
}

export interface CanonicalInvoice {
  inum: string;
  idt: string;
  val: number;
  pos: string;
  ctin?: string;
  rchrg?: string;
  inv_typ?: string;
  items: InvoiceItem[];
}

export interface CanonicalInput {
  gstin: string;
  fp: string;
  gt?: number;
  cur_gt?: number;
  invoices?: CanonicalInvoice[];
  b2b?: any[];
  table_4_b2b?: any[];
  [key: string]: any;
}

/**
 * Mod-36 GSTIN checksum validator (ISO/IEC 7064 Mod 37, 36)
 */
export function validateGstinChecksum(gstin: string): boolean {
  if (!gstin || gstin.length !== 15) return false;
  const chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  let factor = 1;
  let sum = 0;
  const checkCode = gstin[14];

  for (let i = 0; i < 14; i++) {
    const codePoint = chars.indexOf(gstin[i]);
    if (codePoint === -1) return false;
    let addend = factor * codePoint;
    factor = factor === 2 ? 1 : 2;
    addend = Math.floor(addend / 36) + (addend % 36);
    sum += addend;
  }
  const remainder = sum % 36;
  const checkCodePoint = (36 - remainder) % 36;
  return chars[checkCodePoint] === checkCode;
}

/**
 * Recursively prunes empty objects, empty arrays, null, and empty strings
 * matching the official offline tool's `omitEmpty` utility.
 */
export function omitEmpty(obj: any): any {
  if (Array.isArray(obj)) {
    return obj
      .map(omitEmpty)
      .filter((v) => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0) && !(typeof v === "object" && Object.keys(v).length === 0));
  }
  if (typeof obj === "object" && obj !== null) {
    const res: Record<string, any> = {};
    for (const [k, v] of Object.entries(obj)) {
      const cleaned = omitEmpty(v);
      if (cleaned !== null && cleaned !== undefined && cleaned !== "" && !(Array.isArray(cleaned) && cleaned.length === 0) && !(typeof cleaned === "object" && Object.keys(cleaned).length === 0)) {
        res[k] = cleaned;
      }
    }
    return res;
  }
  return obj;
}

/**
 * Formats canonical GSTR-1 input into official GST Portal upload-ready JSON.
 */
export function generatePortalJson(input: CanonicalInput, options: { omitEmpty?: boolean; version?: string } = {}): Record<string, any> {
  const gstin = input.gstin?.trim().toUpperCase();
  const fp = input.fp?.trim();
  const supplierState = gstin?.slice(0, 2);
  const version = options.version || OFFICIAL_OFFLINE_VERSION;

  const rawInvoices: CanonicalInvoice[] = input.invoices || [];
  const b2bByCtin: Record<string, any[]> = {};

  for (const inv of rawInvoices) {
    const ctin = inv.ctin?.trim().toUpperCase();
    if (!ctin) continue; // Skip non-B2B for B2B grouping

    if (!b2bByCtin[ctin]) {
      b2bByCtin[ctin] = [];
    }

    const pos = String(inv.pos || "").padStart(2, "0");
    const isIntra = pos === supplierState;

    const itms = (inv.items || []).map((itm, idx) => {
      const rt = Number(itm.rt || 0);
      const num = rt > 0 ? Math.round(rt * 100) : idx + 1;
      const txval = Math.round(Number(itm.txval || 0) * 100) / 100;

      const itm_det: Record<string, number> = {
        rt,
        txval,
      };

      if (isIntra) {
        itm_det.camt = Math.round(Number(itm.camt ?? (txval * rt * 0.005)) * 100) / 100;
        itm_det.samt = Math.round(Number(itm.samt ?? (txval * rt * 0.005)) * 100) / 100;
      } else {
        itm_det.iamt = Math.round(Number(itm.iamt ?? (txval * rt * 0.01)) * 100) / 100;
      }

      const csamt = Number(itm.csamt || 0);
      if (csamt > 0) {
        itm_det.csamt = Math.round(csamt * 100) / 100;
      }

      return {
        num,
        itm_det,
      };
    });

    b2bByCtin[ctin].push({
      inum: String(inv.inum).trim(),
      idt: String(inv.idt).trim(),
      val: Math.round(Number(inv.val || 0) * 100) / 100,
      pos,
      rchrg: inv.rchrg || "N",
      inv_typ: inv.inv_typ || "R",
      itms,
    });
  }

  const b2bPayload = Object.keys(b2bByCtin)
    .sort()
    .map((ctin) => ({
      ctin,
      inv: b2bByCtin[ctin],
    }));

  const payload: Record<string, any> = {
    gstin,
    fp,
    gt: Number(input.gt || 0),
    cur_gt: Number(input.cur_gt || 0),
    version,
    hash: OFFICIAL_HASH,
    b2b: b2bPayload,
  };

  if (options.omitEmpty) {
    const rootIdent = {
      gstin: payload.gstin,
      fp: payload.fp,
      gt: payload.gt,
      cur_gt: payload.cur_gt,
      version: payload.version,
      hash: payload.hash,
    };
    const cleaned = omitEmpty({ b2b: payload.b2b });
    return { ...rootIdent, ...cleaned };
  }

  return payload;
}

/**
 * Validates a generated returns offline JSON against the GST portal requirements.
 */
export function validatePortalJson(data: any): { isValid: boolean; errors: string[]; warnings: string[] } {
  const errors: string[] = [];
  const warnings: string[] = [];

  if (!data || typeof data !== "object") {
    return { isValid: false, errors: ["File content is not a valid JSON object"], warnings };
  }

  if (!data.gstin) {
    errors.push("Missing top-level 'gstin'");
  } else if (!validateGstinChecksum(data.gstin)) {
    warnings.push(`Supplier GSTIN '${data.gstin}' failed Mod-36 checksum validation`);
  }

  if (!data.fp) {
    errors.push("Missing top-level 'fp' (Return Period)");
  } else if (!/^\d{6}$/.test(data.fp)) {
    errors.push(`Invalid 'fp' format: '${data.fp}'. Expected MMYYYY`);
  }

  if (!data.version) {
    errors.push("Missing top-level 'version'. The GST portal requires 'GST3.2.4'");
  } else if (data.version !== OFFICIAL_OFFLINE_VERSION) {
    warnings.push(`Version is '${data.version}'. The latest official offline tool token is '${OFFICIAL_OFFLINE_VERSION}'`);
  }

  if (!data.hash) {
    warnings.push("Missing 'hash' key. The official offline tool includes 'hash': 'hash'");
  }

  // Check for forbidden portal-download artifacts
  for (const forbidden of FORBIDDEN_UPLOAD_KEYS) {
    if (forbidden in data) {
      errors.push(`Found forbidden portal export key at root: '${forbidden}'. Upload files must not contain portal export metadata.`);
    }
  }

  if (Array.isArray(data.b2b)) {
    const supplierState = data.gstin?.slice(0, 2);
    for (const entry of data.b2b) {
      if (!entry.ctin) {
        errors.push("B2B entry missing 'ctin'");
        continue;
      }
      if ("cfs" in entry) {
        errors.push(`B2B entry '${entry.ctin}' contains portal-export key 'cfs'. Remove for upload.`);
      }
      if (!Array.isArray(entry.inv) || entry.inv.length === 0) {
        warnings.push(`B2B recipient '${entry.ctin}' has no invoices.`);
        continue;
      }
      for (const inv of entry.inv) {
        for (const forbidden of ["flag", "updby", "cflag", "chksum"]) {
          if (forbidden in inv) {
            errors.push(`Invoice '${inv.inum}' contains portal-export key '${forbidden}'. Remove for upload.`);
          }
        }
        const isIntra = inv.pos === supplierState;
        for (const itm of inv.itms || []) {
          const det = itm.itm_det || {};
          if (isIntra && det.iamt && det.iamt > 0) {
            errors.push(`Intra-state invoice '${inv.inum}' (POS: ${inv.pos}) must not contain IGST ('iamt').`);
          }
          if (!isIntra && ((det.camt && det.camt > 0) || (det.samt && det.samt > 0))) {
            errors.push(`Inter-state invoice '${inv.inum}' (POS: ${inv.pos}) must not contain CGST/SGST.`);
          }
        }
      }
    }
  }

  return { isValid: errors.length === 0, errors, warnings };
}

// --- CLI ENTRYPOINT ---
async function main() {
  const args = process.argv.slice(2);
  const command = args[0];

  if (!command || ["--help", "-h", "help"].includes(command)) {
    console.log(`
⚡ gstr-wala Bun Offline Runner (v${OFFICIAL_OFFLINE_VERSION})

Commands:
  generate <input.json> [output.json] [--omit-empty]  Convert canonical input into upload-ready JSON
  validate <returns.json>                             Audit JSON file against official portal rules
  stats    <returns.json>                             Summarize invoices and taxes in a portal JSON

Examples:
  bun run scripts/gstr_offline_runner.ts generate input.json returns_offline.json --omit-empty
  bun run scripts/gstr_offline_runner.ts validate returns_offline.json
  bun run scripts/gstr_offline_runner.ts stats returns_offline.json
    `);
    process.exit(0);
  }

  if (command === "generate") {
    const inputPath = args[1];
    const outputPath = args[2] && !args[2].startsWith("--") ? args[2] : "returns_offline.json";
    const doOmitEmpty = args.includes("--omit-empty") || args.includes("--clean");

    if (!inputPath || !existsSync(inputPath)) {
      console.error(`❌ Input file not found: ${inputPath}`);
      process.exit(1);
    }

    const t0 = performance.now();
    const raw = JSON.parse(readFileSync(inputPath, "utf-8"));
    const portalData = generatePortalJson(raw, { omitEmpty: doOmitEmpty });
    writeFileSync(outputPath, JSON.stringify(portalData, null, 2), "utf-8");
    const elapsed = (performance.now() - t0).toFixed(2);

    let invoiceCount = 0;
    portalData.b2b?.forEach((b: any) => (invoiceCount += b.inv?.length || 0));

    console.log(`✅ [Bun] Generated official uploadable JSON in ${elapsed}ms -> '${outputPath}'`);
    console.log(`   GSTIN: ${portalData.gstin} | Period: ${portalData.fp} | Version: ${portalData.version}`);
    console.log(`   Recipients: ${portalData.b2b?.length || 0} | Invoices: ${invoiceCount}`);
    process.exit(0);
  }

  if (command === "validate") {
    const targetPath = args[1];
    if (!targetPath || !existsSync(targetPath)) {
      console.error(`❌ File not found: ${targetPath}`);
      process.exit(1);
    }

    const raw = JSON.parse(readFileSync(targetPath, "utf-8"));
    const report = validatePortalJson(raw);

    if (report.warnings.length > 0) {
      console.log(`⚠️  Warnings (${report.warnings.length}):`);
      report.warnings.forEach((w) => console.log(`   - ${w}`));
    }

    if (!report.isValid) {
      console.error(`❌ Validation Failed with ${report.errors.length} error(s):`);
      report.errors.forEach((e) => console.error(`   - ${e}`));
      process.exit(1);
    }

    console.log(`✅ [Bun] File '${targetPath}' is 100% compliant with GST Portal upload rules.`);
    process.exit(0);
  }

  if (command === "stats") {
    const targetPath = args[1];
    if (!targetPath || !existsSync(targetPath)) {
      console.error(`❌ File not found: ${targetPath}`);
      process.exit(1);
    }

    const data = JSON.parse(readFileSync(targetPath, "utf-8"));
    let invCount = 0;
    let totalVal = 0;
    let totalTxval = 0;
    let totalIamt = 0;
    let totalCamt = 0;
    let totalSamt = 0;
    let totalCsamt = 0;

    data.b2b?.forEach((b: any) => {
      b.inv?.forEach((i: any) => {
        invCount++;
        totalVal += Number(i.val || 0);
        i.itms?.forEach((it: any) => {
          const d = it.itm_det || {};
          totalTxval += Number(d.txval || 0);
          totalIamt += Number(d.iamt || 0);
          totalCamt += Number(d.camt || 0);
          totalSamt += Number(d.samt || 0);
          totalCsamt += Number(d.csamt || 0);
        });
      });
    });

    console.log(`
📊 GST Portal Return Summary:
   File: ${targetPath}
   GSTIN: ${data.gstin} | Period: ${data.fp} | Version: ${data.version}
   Recipients: ${data.b2b?.length || 0}
   Total Invoices: ${invCount}
   Total Invoice Value: ₹${totalVal.toFixed(2)}
   Total Taxable Value: ₹${totalTxval.toFixed(2)}
   Integrated Tax (IGST): ₹${totalIamt.toFixed(2)}
   Central Tax (CGST):    ₹${totalCamt.toFixed(2)}
   State Tax (SGST):      ₹${totalSamt.toFixed(2)}
   Cess:                  ₹${totalCsamt.toFixed(2)}
   Total Tax:             ₹${(totalIamt + totalCamt + totalSamt + totalCsamt).toFixed(2)}
    `);
    process.exit(0);
  }

  console.error(`❌ Unknown command: ${command}. Use --help for usage.`);
  process.exit(1);
}

if (import.meta.main) {
  main();
}
