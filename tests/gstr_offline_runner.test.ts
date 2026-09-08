import { describe, it, expect } from "bun:test";
import {
  validateGstinChecksum,
  omitEmpty,
  generatePortalJson,
  validatePortalJson,
  OFFICIAL_OFFLINE_VERSION,
  OFFICIAL_HASH
} from "../scripts/gstr_offline_runner";

describe("Bun GSTR Offline Tool Runner", () => {
  it("validates Mod-36 GSTIN checksum correctly", () => {
    // Valid GSTINs
    expect(validateGstinChecksum("09AXBPS5714M1ZZ")).toBe(true);
    expect(validateGstinChecksum("27AAAAA0000A1Z2")).toBe(true);
    expect(validateGstinChecksum("07ACIFA6125A1ZW")).toBe(true);

    // Invalid GSTINs
    expect(validateGstinChecksum("09AXBPS5714M1Z9")).toBe(false);
    expect(validateGstinChecksum("INVALID")).toBe(false);
  });

  it("omits empty objects, empty arrays, and empty strings recursively", () => {
    const raw = {
      keepNumber: 0,
      keepFloat: 0.0,
      keepBool: false,
      removeEmptyStr: "",
      removeEmptyArr: [],
      removeEmptyObj: {},
      nested: {
        removeEmptyArr: [],
        keepVal: "ok"
      }
    };
    const cleaned = omitEmpty(raw);
    expect(cleaned).toEqual({
      keepNumber: 0,
      keepFloat: 0.0,
      keepBool: false,
      nested: {
        keepVal: "ok"
      }
    });
  });

  it("generates upload-ready portal JSON matching official offline tool spec", () => {
    const sampleInput = {
      gstin: "09AXBPS5714M1ZZ",
      fp: "082026",
      gt: 0,
      cur_gt: 0,
      invoices: [
        {
          inum: "194",
          idt: "06-08-2026",
          val: 29500,
          pos: "05",
          ctin: "05AAXFP5987C1ZM",
          rchrg: "N",
          inv_typ: "R",
          items: [
            {
              txval: 25000,
              rt: 18,
              iamt: 4500
            }
          ]
        },
        {
          inum: "195",
          idt: "06-08-2026",
          val: 2596,
          pos: "09",
          ctin: "09AALCB7404R1ZZ",
          rchrg: "N",
          inv_typ: "R",
          items: [
            {
              txval: 2200,
              rt: 18,
              camt: 198,
              samt: 198
            }
          ]
        }
      ]
    };

    const output = generatePortalJson(sampleInput, { omitEmpty: true });
    expect(output.version).toBe(OFFICIAL_OFFLINE_VERSION);
    expect(output.hash).toBe(OFFICIAL_HASH);
    expect(output.gstin).toBe("09AXBPS5714M1ZZ");
    expect(output.fp).toBe("082026");
    expect(output.b2b.length).toBe(2);

    // Validate using validatePortalJson
    const valResult = validatePortalJson(output);
    expect(valResult.isValid).toBe(true);
    expect(valResult.errors.length).toBe(0);
  });

  it("catches forbidden portal download fields in upload validator", () => {
    const badUpload = {
      gstin: "09AXBPS5714M1ZZ",
      fp: "082026",
      filing_typ: "M", // Forbidden
      b2b: [
        {
          ctin: "07ACIFA6125A1ZW",
          cfs: "N", // Forbidden
          inv: [
            {
              inum: "101",
              val: 1000,
              pos: "07",
              flag: "U", // Forbidden
              updby: "S", // Forbidden
              chksum: "some_hash" // Forbidden
            }
          ]
        }
      ]
    };

    const valResult = validatePortalJson(badUpload);
    expect(valResult.isValid).toBe(false);
    expect(valResult.errors.some((e) => e.includes("filing_typ"))).toBe(true);
    expect(valResult.errors.some((e) => e.includes("cfs"))).toBe(true);
    expect(valResult.errors.some((e) => e.includes("flag"))).toBe(true);
    expect(valResult.errors.some((e) => e.includes("chksum"))).toBe(true);
  });
});
