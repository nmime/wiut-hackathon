# Business transaction imports

Workspaces start empty. An administrator or officer can import a business from
CSV or JSON on the Businesses page. Imported records belong only to the active
workspace. Upload at most 5 MB and 20,000 transactions per business.

CSV uses these exact required headers:

```csv
ts,direction,channel,amount
2026-09-01T12:00:00Z,in,transfer,2500000
2026-09-02T12:00:00Z,out,transfer,900000
```

The two illustrative rows explain the format; they are not borrower evidence.
Enter the business name, sector and location alongside the CSV. Supported
directions are `in` and `out`; channels are `card`, `transfer`, `qr`, `cash_in`
and `other`. Dates must be valid ISO timestamps. Amounts are positive, finite
UZS values between 1e-12 and 1e12. Invalid rows produce actionable errors;
the application does not silently repair or import a partial file.

JSON contains the business metadata and transactions together:

```json
{
  "name": "Business name",
  "sector": "Retail",
  "location": "Tashkent",
  "data_source": "user_provided",
  "amount_unit": "UZS",
  "transactions": [
    {
      "ts": "2026-09-01T12:00:00Z",
      "direction": "in",
      "channel": "transfer",
      "amount": 2500000
    }
  ]
}
```

The API maps `amount` directly to its unchanged ML transport field
`amount_index`: **one internal unit equals one UZS** for this import. Business
and assessment metadata retain that declaration, so UI charts, downloads and
recommendations use UZS. Legacy synthetic cases keep index units. Their archived
records and original results remain available through tenant-scoped saved links.

Download Business JSON includes the import fields again. Transaction CSV uses
the same headers as the upload. Both can be imported into another workspace by
an authorized user. An assessment JSON download retains the raw, validated model
response and its assessment-unit snapshot; monetary transport field names still
end in `_index`.

The importer declares the source; the MVP does not authenticate bank statements
or deduplicate repeated uploads. Review the business history and file origin.
The final scorer checks an optional requested amount against the capacity of
the seasonal schedule it actually offers. Its terms disclose 24% nominal annual
interest, total interest and repayment. Forecast provenance identifies the
real-trained revenue component and observed-cost projection; it uses no
synthetic net forecast. Capacity scores are neither default probabilities nor
guarantees about future repayments.
