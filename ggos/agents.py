"""36 agents for NoLoveAppeal store work — report-only, approval-gated.

What this module IS:
  - 36 distinct agents, each with one job, each computing from the
    store context it is actually given (a dict/list of products, and
    optionally orders / sessions / inbox data). No random numbers, no
    canned copy presented as fact, no network calls, no Shopify client.
  - A swarm runner that runs them in order, aggregates their findings,
    and builds ONE change package that is always ``approved=False`` and
    ``applied=False`` when it leaves this code.

What this module is NOT:
  - It never writes to Shopify. There is no Shopify API call in this
    file. ``apply_package()`` always raises, by design: the package is
    pasted to Muse in chat, Muse checks it against the live store
    (after Shopify is reconnected), shows the exact changes, and only
    pushes what the owner approves there.
  - It never sends a post, DM, or email, never spends money, and never
    invents a spec. Anything missing (fabric, GSM, size chart, cost,
    launch date, discount %) is reported as blocked / needs_owner,
    never filled in with a guess.
  - It is not a live store read. The context is a snapshot the caller
    supplies. If the snapshot is stale, the findings are stale — the
    report says so, in ``context_source`` / ``context_date`` when given.

Organic-only rule (from the owner, 2026-10-27): no paid ads, boosts,
or paid features are ever proposed by these agents. A discount code
is only proposed with percentage / audience / dates marked TBD for
the owner to supply.

Usage (phone-friendly, no server needed):
  python -m ggos.agents --context store_context.json --out report.json
  # store_context.json: {"products": [...], "orders": [...], ...}
  # or just a bare list of products.
"""
import argparse
import json
import re
from dataclasses import dataclass, field

from . import database as db

# ---------------------------------------------------------------- helpers


def _products(context):
    if isinstance(context, dict):
        return context.get("products") or []
    if isinstance(context, list):
        return context
    return []


def _title(p):
    return str(p.get("title") or "")


def _handle(p):
    return str(p.get("handle") or "")


def _status(p):
    return str(p.get("status") or "")


def _price(p):
    """Best price actually present, or None. Never invents one."""
    try:
        amt = p.get("priceRangeV2", {}).get("minVariantPrice", {}).get("amount")
        if amt is not None:
            return float(amt)
    except (AttributeError, TypeError, ValueError):
        pass
    for v in p.get("variants", {}).get("edges", []) or []:
        try:
            return float(v["node"]["price"])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _variants(p):
    out = []
    for v in p.get("variants", {}).get("edges", []) or []:
        node = v.get("node") or {}
        out.append(node)
    return out


def _variant_titles(p):
    return [str(v.get("title") or "") for v in _variants(p)]


def _skus(p):
    return [v.get("sku") for v in _variants(p) if v.get("sku")]


def _has_image(p):
    fm = p.get("featuredMedia")
    if not fm:
        return False
    if isinstance(fm, dict):
        return bool(fm.get("preview"))
    return bool(fm)


def _base_handle(handle):
    return re.sub(r"-1$", "", handle)


def _result(agent, findings=None, proposed=None, blocked=None, needs=None, counts=None):
    return {
        "agent": agent.name,
        "role": agent.role,
        "team": agent.team,
        "findings": findings or [],
        "proposed_changes": proposed or [],
        "blocked": blocked or [],
        "needs_owner": needs or [],
        "counts": counts or {},
    }


# ---------------------------------------------------------------- base


class BaseAgent:
    name = "base"
    role = "base"
    team = "base"
    # No agent in this file writes anywhere except the local audit DB.
    writes_to_shopify = False

    def check(self, context):
        raise NotImplementedError

    def run(self, context, db_path=None):
        result = self.check(context)
        if db_path is not None:
            db.init_db(db_path)
            conn = db.get_connection(db_path)
            try:
                cur = conn.execute(
                    "INSERT INTO agent_runs (agent_name, status, summary)"
                    " VALUES (?, 'done', ?)",
                    (self.name, json.dumps(result)),
                )
                conn.execute(
                    "UPDATE agent_runs SET finished_at = datetime('now')"
                    " WHERE id = ?",
                    (cur.lastrowid,),
                )
                db.insert_event(
                    conn, "agent_run", agent_name=self.name,
                    description=f"{self.name}: {len(result['findings'])} finding(s)",
                )
                conn.commit()
            finally:
                conn.close()
        return result


# ---------------------------------------------------------------- audit team


class Analyst(BaseAgent):
    name = "Analyst"
    role = "Duplicate audit: group drafts by title and by base handle"
    team = "audit"

    def check(self, context):
        prods = _products(context)
        by_title = {}
        for p in prods:
            by_title.setdefault(_title(p).strip().lower(), []).append(p)
        pairs = []
        for title, group in by_title.items():
            if len(group) > 1:
                pairs.append({
                    "title": group[0].get("title"),
                    "count": len(group),
                    "products": [
                        {"id": g.get("id"), "handle": _handle(g),
                         "status": _status(g), "variants": _variant_titles(g)}
                        for g in group
                    ],
                })
        findings = [f"{len(pairs)} duplicate title group(s) in context of "
                    f"{len(prods)} product(s)"]
        for pair in pairs:
            findings.append(
                f"DUPLICATE: {pair['title']} x{pair['count']} — "
                + ", ".join(x["handle"] for x in pair["products"]))
        return _result(self, findings=findings, counts={
            "products": len(prods), "duplicate_groups": len(pairs)},
            blocked=[] if pairs else ["No duplicate title groups found in this context"],
            needs=["Owner picks the keeper for each duplicate pair; no delete is proposed as decided"])


class CatalogAgent(BaseAgent):
    name = "CatalogAgent"
    role = "Merge proposal: keeper trade-off per duplicate pair, no delete decided"
    team = "audit"

    def check(self, context):
        prods = _products(context)
        by_title = {}
        for p in prods:
            by_title.setdefault(_title(p).strip().lower(), []).append(p)
        proposed, findings, needs = [], [], []
        for title, group in by_title.items():
            if len(group) < 2:
                continue
            # Earliest + clean handle is usually group[0] in snapshot order;
            # most variants wins on completeness. Report both, decide neither.
            richest = max(group, key=lambda g: len(_variant_titles(g)))
            cleanest = [g for g in group if not _handle(g).endswith("-1")]
            findings.append(
                f"MERGE CANDIDATE: {_title(group[0])}: clean-handle copy "
                f"{_handle(cleanest[0]) if cleanest else '?'} vs richest copy "
                f"{_handle(richest)} ({len(_variant_titles(richest))} variants)")
            proposed.append({
                "action": "merge_duplicates_UNDECIDED",
                "title": _title(group[0]),
                "keep_clean_handle": _handle(cleanest[0]) if cleanest else None,
                "keep_richest": _handle(richest),
                "note": "Owner must pick one; the other is deleted only after that pick.",
            })
            needs.append(f"Keeper pick for {_title(group[0])}")
        return _result(self, findings=findings, proposed=proposed, needs=needs,
                       counts={"merge_candidates": len(proposed)})


class PriceLadder(BaseAgent):
    name = "PriceLadder"
    role = "Price-ladder check: live vs Wave 2 gaps, no price invented"
    team = "audit"

    def check(self, context):
        prods = _products(context)
        live_tees = [ _price(p) for p in prods
                      if _status(p) == "ACTIVE" and _price(p) is not None
                      and "tee" in _title(p).lower() ]
        wave_tees = [ _price(p) for p in prods
                      if _status(p) == "DRAFT" and _price(p) is not None
                      and "tee" in _title(p).lower() ]
        findings, needs = [], []
        if live_tees and wave_tees:
            gap = min(wave_tees) - min(live_tees)
            findings.append(f"Live tee floor ${min(live_tees):.2f}, Wave 2 tee floor "
                            f"${min(wave_tees):.2f}, gap ${gap:.2f}")
            if gap != 0:
                needs.append("Owner confirms whether the Wave 2 tee gap is intentional")
        else:
            findings.append("Price-ladder comparison blocked: live or Wave 2 tee prices missing from context")
        return _result(self, findings=findings, needs=needs, counts={
            "live_tees": len(live_tees), "wave2_tees": len(wave_tees)})


class SkuAuditor(BaseAgent):
    name = "SkuAuditor"
    role = "SKU audit: missing, spaced, and duplicated SKUs"
    team = "audit"

    def check(self, context):
        prods = _products(context)
        missing, spaced, seen, dupes = [], [], {}, []
        for p in prods:
            for v in _variants(p):
                sku = v.get("sku")
                if not sku:
                    missing.append(f"{_title(p)} {v.get('title')}")
                elif " " in str(sku):
                    spaced.append(f"{_title(p)}: {sku}")
                elif sku in seen:
                    dupes.append(f"SKU {sku}: {_title(p)} and {seen[sku]}")
                else:
                    seen[sku] = _title(p)
        findings = ([f"Missing SKU on {m}" for m in missing]
                    + [f"Spaced SKU {s}" for s in spaced]
                    + [f"Duplicate SKU {d}" for d in dupes])
        return _result(self, findings=findings or ["No SKU problems in context"],
                       counts={"missing_sku_variants": len(missing),
                               "spaced_skus": len(spaced), "duplicate_skus": len(dupes)})


class ImageAuditor(BaseAgent):
    name = "ImageAuditor"
    role = "Image audit: products with no featured media"
    team = "audit"

    def check(self, context):
        prods = _products(context)
        no_img = [p for p in prods if not _has_image(p)]
        findings = [f"{len(no_img)} of {len(prods)} products have no featured image"]
        findings += [f"NO IMAGE: {_title(p)} ({_status(p)})" for p in no_img]
        return _result(self, findings=findings, counts={
            "products": len(prods), "no_image": len(no_img)},
            blocked=["Launch blocked for image-less products until images are supplied"] if no_img else [])


class DescriptionAuditor(BaseAgent):
    name = "DescriptionAuditor"
    role = "Description audit: empty descriptions"
    team = "audit"

    def check(self, context):
        prods = _products(context)
        empty = [p for p in prods if not (p.get("description") or "").strip()]
        findings = [f"{len(empty)} products have an empty description"]
        findings += [f"EMPTY DESCRIPTION: {_title(p)} ({_status(p)})" for p in empty]
        return _result(self, findings=findings, counts={"empty_descriptions": len(empty)})


class VariantAuditor(BaseAgent):
    name = "VariantAuditor"
    role = "Variant audit: size ranges per product"
    team = "audit"

    def check(self, context):
        prods = _products(context)
        findings = []
        for p in prods:
            findings.append(f"{_title(p)}: {', '.join(_variant_titles(p)) or 'no variants'}")
        return _result(self, findings=findings, counts={"products": len(prods)})


class HandleAuditor(BaseAgent):
    name = "HandleAuditor"
    role = "Handle audit: -1 suffix duplicates"
    team = "audit"

    def check(self, context):
        prods = _products(context)
        suffixed = [p for p in prods if _handle(p).endswith("-1")]
        findings = [f"{len(suffixed)} handles end in -1"]
        findings += [f"-1 HANDLE: {_handle(p)} ({_title(p)})" for p in suffixed]
        return _result(self, findings=findings, counts={"minus_one_handles": len(suffixed)})


class TagAuditor(BaseAgent):
    name = "TagAuditor"
    role = "Tag audit: Wave 2 tags, untagged products"
    team = "audit"

    def check(self, context):
        prods = _products(context)
        untagged = [p for p in prods if not p.get("tags")]
        wave2 = [p for p in prods if "Wave 2" in (p.get("tags") or [])]
        findings = [f"{len(wave2)} Wave 2 tagged, {len(untagged)} untagged"]
        findings += [f"UNTAGGED: {_title(p)}" for p in untagged]
        return _result(self, findings=findings, counts={
            "wave2_tagged": len(wave2), "untagged": len(untagged)})


# ---------------------------------------------------------------- catalog / creative


class CollectionPlanner(BaseAgent):
    name = "CollectionPlanner"
    role = "Collection proposal only: Wave 2 draft collection, hidden until launch"
    team = "catalog"

    def check(self, context):
        prods = _products(context)
        wave2 = [p for p in prods if "Wave 2" in (p.get("tags") or [])]
        proposed = [{
            "action": "create_collection_DRAFT_ONLY",
            "title": "Wave 2",
            "visibility": "hidden until owner launch date",
            "product_count_in_context": len(wave2),
            "note": "Draft only. No collection is created by this code.",
        }] if wave2 else []
        return _result(self, findings=[f"{len(wave2)} Wave 2 products would go in a Wave 2 collection"],
                       proposed=proposed, needs=["Owner launch date for Wave 2"] if wave2 else [],
                       counts={"wave2_products": len(wave2)})


class DiscountAuditor(BaseAgent):
    name = "DiscountAuditor"
    role = "Discount audit: only codes present in context are reported"
    team = "catalog"

    def check(self, context):
        codes = []
        if isinstance(context, dict):
            codes = context.get("discounts") or []
        findings = ([f"Discount in context: {c}" for c in codes]
                    if codes else ["No discount codes in context — liveness is UNVERIFIED, not zero"])
        return _result(self, findings=findings, counts={"discounts_in_context": len(codes)},
                       blocked=[] if codes else ["Discount liveness cannot be verified from this context"])


class CreativeDirector(BaseAgent):
    name = "CreativeDirector"
    role = "Creative direction: copy + shot needs for image-less products, specs as placeholders"
    team = "creative"

    def check(self, context):
        prods = _products(context)
        no_img = [p for p in prods if not _has_image(p)]
        findings = [f"CREATIVE NEEDED: {_title(p)} — front flat, back flat, detail, worn"
                    for p in no_img]
        needs = ["Artwork files for every image-less product",
                 "Owner approves or edits all copy before it goes live"]
        return _result(self, findings=findings or ["No image-less products in context"],
                       needs=needs, counts={"creative_needed": len(no_img)})


class BrandVoice(BaseAgent):
    name = "BrandVoice"
    role = "Brand-voice check: heavyweight claims need a GSM number, or they are flagged"
    team = "creative"

    def check(self, context):
        prods = _products(context)
        findings, needs = [], []
        for p in prods:
            desc = (p.get("description") or "").lower()
            if "heavyweight" in desc and not re.search(r"\d+\s*(gsm|oz)", desc):
                findings.append(f"HEAVYWEIGHT UNVERIFIED: {_title(p)} — no GSM/oz in description")
                needs.append(f"GSM figure for {_title(p)} before calling it heavyweight")
        return _result(self, findings=findings or ["No unverified heavyweight claims in context"],
                       needs=needs, counts={"heavyweight_flags": len(findings)})


class ShotList(BaseAgent):
    name = "ShotList"
    role = "Shot list: 4 shots per image-less product"
    team = "creative"

    def check(self, context):
        prods = _products(context)
        no_img = [p for p in prods if not _has_image(p)]
        findings = [f"{_title(p)}: front flat, back flat, detail, worn" for p in no_img]
        return _result(self, findings=findings, counts={
            "products_needing_shots": len(no_img), "shots_total": 4 * len(no_img)})


class MockupBrief(BaseAgent):
    name = "MockupBrief"
    role = "Mockup brief: square + 4:5, mockups are not photographed product"
    team = "creative"

    def check(self, context):
        prods = _products(context)
        no_img = [p for p in prods if not _has_image(p)]
        findings = [f"MOCKUP BRIEF: {_title(p)} — square + 4:5, dark ground, match confirmed blank colour only"
                    for p in no_img]
        return _result(self, findings=findings,
                       needs=["Blank colour confirmation before mockups are matched to it"],
                       counts={"mockups_needed": len(no_img)})


# ---------------------------------------------------------------- manufacturing


class ManufacturingLead(BaseAgent):
    name = "ManufacturingLead"
    role = "Manufacturing checklist: blank, fabric, print, sizes, lead time, cost — all TO CONFIRM"
    team = "manufacturing"

    def check(self, context):
        prods = _products(context)
        checklist = ["blank brand/style", "fabric composition + GSM/oz", "colourways",
                     "print method + placement", "size range + size chart",
                     "lead time", "MOQ", "unit cost", "inbound shipping",
                     "labels + care + country of origin"]
        findings = []
        for p in prods:
            if _status(p) == "DRAFT":
                findings.append(f"SPEC CHECKLIST: {_title(p)} — " + "; ".join(checklist) + " — TO CONFIRM")
        return _result(self, findings=findings,
                       needs=["Supplier answers for every checklist item; no spec is stated until confirmed"],
                       counts={"drafts_needing_specs": len([p for p in prods if _status(p) == 'DRAFT'])})


class BlankSpec(BaseAgent):
    name = "BlankSpec"
    role = "Blank spec check: blank type is not in product context, so it is flagged missing"
    team = "manufacturing"

    def check(self, context):
        prods = _products(context)
        missing = [p for p in prods if not p.get("blank")]
        return _result(self, findings=[f"BLANK MISSING: {_title(p)}" for p in missing],
                       needs=["Blank brand + style number per product, from the supplier"],
                       counts={"blank_missing": len(missing)})


class PrintMethod(BaseAgent):
    name = "PrintMethod"
    role = "Print-method check: method is not in product context, so it is flagged missing"
    team = "manufacturing"

    def check(self, context):
        prods = _products(context)
        missing = [p for p in prods if not p.get("print_method")]
        return _result(self, findings=[f"PRINT METHOD MISSING: {_title(p)}" for p in missing],
                       needs=["Print method per placement, from the supplier"],
                       counts={"print_method_missing": len(missing)})


class SizeChart(BaseAgent):
    name = "SizeChart"
    role = "Size-chart check: chart is not in product context, so it is flagged missing"
    team = "manufacturing"

    def check(self, context):
        prods = _products(context)
        missing = [p for p in prods if not p.get("size_chart")]
        return _result(self, findings=[f"SIZE CHART MISSING: {_title(p)}" for p in missing],
                       needs=["Size chart with measurements per product"],
                       counts={"size_chart_missing": len(missing)})


class LeadTime(BaseAgent):
    name = "LeadTime"
    role = "Lead-time check: sample / production / shipping times are not in context"
    team = "manufacturing"

    def check(self, context):
        prods = _products(context)
        return _result(self, findings=[f"LEAD TIME MISSING: {_title(p)}" for p in prods],
                       needs=["Sample, production, and shipping lead times per item"],
                       counts={"lead_time_missing": len(prods)})


class CostMargin(BaseAgent):
    name = "CostMargin"
    role = "Cost/margin check: prices listed, costs missing, margin is UNVERIFIED"
    team = "manufacturing"

    def check(self, context):
        prods = _products(context)
        findings = []
        for p in prods:
            price = _price(p)
            if price is not None:
                findings.append(f"{_title(p)}: price ${price:.2f}, unit cost NOT IN CONTEXT, margin UNVERIFIED")
        return _result(self, findings=findings,
                       blocked=["Margin cannot be computed until unit costs arrive"],
                       counts={"priced_products": len(findings)})


# ---------------------------------------------------------------- growth / ops


class GrowthMarketer(BaseAgent):
    name = "GrowthMarketer"
    role = "Launch plan draft: teaser + launch-day sequence, dates and discount % TBD"
    team = "growth"

    def check(self, context):
        prods = _products(context)
        wave2 = [p for p in prods if "Wave 2" in (p.get("tags") or [])]
        launch = context.get("launch_date") if isinstance(context, dict) else None
        findings = ["T-7 teaser, T-5 detail, T-3 waitlist email, T-1 silhouettes, launch-day email/social/reminder"]
        if not launch:
            findings.append("Launch date NOT IN CONTEXT — sequence dates cannot be set")
        proposed = [{
            "action": "create_discount_DRAFT_ONLY",
            "code": "WAVE2EARLY",
            "percentage": "TBD — owner to supply",
            "audience": "TBD — owner to supply",
            "note": "No discount is created by this code. Organic only: no paid ads proposed.",
        }]
        return _result(self, findings=findings, proposed=proposed,
                       needs=["Launch date", "WAVE2EARLY percentage + audience + dates"],
                       counts={"wave2_products": len(wave2)})


class TeaserPlanner(BaseAgent):
    name = "TeaserPlanner"
    role = "Teaser plan: one teaser per Wave 2 product, no product name before T-3"
    team = "growth"

    def check(self, context):
        prods = _products(context)
        wave2 = [p for p in prods if "Wave 2" in (p.get("tags") or [])]
        return _result(self, findings=[f"TEASER: {_title(p)}" for p in wave2],
                       counts={"teasers": len(wave2)})


class EmailPlanner(BaseAgent):
    name = "EmailPlanner"
    role = "Email plan only: subjects drafted, nothing sent"
    team = "growth"

    def check(self, context):
        return _result(self, findings=[
            "Launch email subject (draft, not sent): Wave 2. Now open.",
            "Last-call email subject (draft, not sent): Wave 2 does not wait."],
            blocked=["No email is sent by this code"],
            counts={"email_drafts": 2})


class SocialPlanner(BaseAgent):
    name = "SocialPlanner"
    role = "Social plan only: copy drafted, nothing posted"
    team = "growth"

    def check(self, context):
        return _result(self, findings=[
            "Social draft (not posted): No love. Still here. Wave 2 is live.",
            "Social draft (not posted): Trust nothing. Move anyway.",
            "Social draft (not posted): Heartless by choice."],
            blocked=["No post is published by this code"],
            counts={"social_drafts": 3})


class DmFunnel(BaseAgent):
    name = "DmFunnel"
    role = "DM funnel plan only: follow-ups drafted, nothing sent, no re-send of openers"
    team = "growth"

    def check(self, context):
        return _result(self, findings=["DM funnel is draft-only; opener re-sends are forbidden by the owner rule"],
                       blocked=["No DM is sent by this code"],
                       counts={"dm_drafts": 0})


class ReplyTriage(BaseAgent):
    name = "ReplyTriage"
    role = "Reply triage: needs live inbox data, otherwise blocked"
    team = "growth"

    def check(self, context):
        inbox = context.get("inbox") if isinstance(context, dict) else None
        if not inbox:
            return _result(self, findings=["No inbox data in context"],
                           blocked=["Reply triage cannot run without live inbox data"],
                           counts={"replies": 0})
        return _result(self, findings=[f"{len(inbox)} inbox thread(s) in context"],
                       counts={"replies": len(inbox)})


class OrderWatch(BaseAgent):
    name = "OrderWatch"
    role = "Order watch: counts orders actually in context, never assumes zero"
    team = "ops"

    def check(self, context):
        orders = context.get("orders") if isinstance(context, dict) else None
        if orders is None:
            return _result(self, findings=["No order data in context — orders are UNVERIFIED, not zero"],
                           blocked=["Order count cannot be verified from this context"],
                           counts={"orders_in_context": 0})
        return _result(self, findings=[f"{len(orders)} order(s) in context"],
                       counts={"orders_in_context": len(orders)})


class StoreWatch(BaseAgent):
    name = "StoreWatch"
    role = "Store watch: counts sessions only if present in context"
    team = "ops"

    def check(self, context):
        sessions = context.get("sessions") if isinstance(context, dict) else None
        if sessions is None:
            return _result(self, findings=["No session data in context — traffic is UNVERIFIED, not zero"],
                           blocked=["Session count cannot be verified from this context"],
                           counts={"sessions_in_context": 0})
        return _result(self, findings=[f"{len(sessions)} session record(s) in context"],
                       counts={"sessions_in_context": len(sessions)})


class FinanceLedger(BaseAgent):
    name = "FinanceLedger"
    role = "Finance ledger: integer cents only, from orders actually in context"
    team = "ops"

    def check(self, context):
        orders = context.get("orders") if isinstance(context, dict) else None
        if orders is None:
            return _result(self, findings=["No order data — revenue is UNVERIFIED, not $0"],
                           blocked=["Revenue cannot be computed without order data"],
                           counts={"orders_in_context": 0})
        total_cents = 0
        for o in orders:
            try:
                total_cents += int(round(float(o.get("total", 0)) * 100))
            except (TypeError, ValueError):
                continue
        return _result(self, findings=[f"Revenue in context: {total_cents} cents from {len(orders)} order(s)"],
                       counts={"revenue_cents": total_cents, "orders_in_context": len(orders)})


class ComplianceShield(BaseAgent):
    name = "ComplianceShield"
    role = "Compliance scan: flags banned claims in descriptions"
    team = "ops"

    def check(self, context):
        banned = ["cpr cert", "certified", "heals", "cures", "guaranteed results", "proven to"]
        findings = []
        for p in _products(context):
            desc = (p.get("description") or "").lower()
            for word in banned:
                if word in desc:
                    findings.append(f"COMPLIANCE FLAG: {_title(p)} contains '{word}' — owner must review")
        return _result(self, findings=findings or ["No banned-claim keywords found in descriptions"],
                       counts={"compliance_flags": len(findings)})


class RiskOfficer(BaseAgent):
    name = "RiskOfficer"
    role = "Approval gate: a change without owner approval on file is blocked"
    team = "ops"

    def check(self, context):
        approved = False
        if isinstance(context, dict):
            approved = bool(context.get("owner_approved"))
        findings = ["Approval gate: owner_approved = " + str(approved)]
        blocked = [] if approved else ["No owner approval on file in this run — nothing may be applied"]
        return _result(self, findings=findings, blocked=blocked, counts={"approved": int(approved)})


class InventoryTracker(BaseAgent):
    name = "InventoryTracker"
    role = "Inventory check: totals actually in context, Printful sync unknown unless stated"
    team = "ops"

    def check(self, context):
        prods = _products(context)
        zero = [p for p in prods if (p.get("totalInventory") or 0) == 0]
        findings = [f"{len(zero)} of {len(prods)} products show totalInventory 0 in context"]
        findings.append("Printful sync status is UNVERIFIED unless the context states it per product")
        return _result(self, findings=findings, counts={
            "products": len(prods), "zero_inventory": len(zero)})


class SupplierLiaison(BaseAgent):
    name = "SupplierLiaison"
    role = "Supplier liaison: email checklist draft for the founder to send"
    team = "manufacturing"

    def check(self, context):
        return _result(self, findings=[
            "Supplier email draft (not sent): blank, fabric, print, sizes, lead time, MOQ, unit cost, shipping, labels"],
            blocked=["No supplier email is sent by this code"],
            counts={"supplier_checklists": 1})


class CustomerService(BaseAgent):
    name = "CustomerService"
    role = "Customer service: FAQ needs owner answers, nothing sent to customers"
    team = "ops"

    def check(self, context):
        return _result(self, findings=["FAQ draft needs owner answers for shipping, made-to-order timing, and returns"],
                       blocked=["No customer message is sent by this code"],
                       needs=["Made-to-order timing wording", "Returns wording"],
                       counts={"faq_drafts": 1})


# ---------------------------------------------------------------- commander + runner


class SwarmCommander(BaseAgent):
    name = "SwarmCommander"
    role = "Commander: runs agents in order, builds one change package, never applies it"
    team = "command"

    def check(self, context):
        others = [cls.name for cls in AGENT_CLASSES if cls is not SwarmCommander]
        return _result(self, findings=[f"Swarm roster (excluding commander): {len(others)} agents"],
                       counts={"agents_excluding_commander": len(others), "total_agents": len(AGENT_CLASSES)})


# Registry order: the original five first, then the rest, commander last.
AGENT_CLASSES = [
    Analyst, CatalogAgent, CreativeDirector, ManufacturingLead, GrowthMarketer,
    PriceLadder, SkuAuditor, ImageAuditor, DescriptionAuditor, VariantAuditor,
    HandleAuditor, TagAuditor, CollectionPlanner, DiscountAuditor, BrandVoice,
    ShotList, MockupBrief, BlankSpec, PrintMethod, SizeChart, LeadTime,
    CostMargin, TeaserPlanner, EmailPlanner, SocialPlanner, DmFunnel,
    ReplyTriage, OrderWatch, StoreWatch, FinanceLedger, ComplianceShield,
    RiskOfficer, InventoryTracker, SupplierLiaison, CustomerService,
    SwarmCommander,
]


def list_agents():
    """Return the 36-agent roster as name/role/team dicts."""
    return [{"name": cls.name, "role": cls.role, "team": cls.team}
            for cls in AGENT_CLASSES]


def run_swarm(context, db_path=None):
    """Run all 36 agents in registry order on the given context.

    Returns a change package that is ALWAYS unapproved and unapplied
    when it leaves this function. Approval happens in chat with the
    owner, and the push happens there, not here.
    """
    results = []
    for cls in AGENT_CLASSES:
        agent = cls()
        try:
            results.append(agent.run(context, db_path=db_path))
        except Exception as exc:  # one agent must not kill the swarm report
            results.append(_result(agent, findings=[f"AGENT FAILED: {exc!r}"],
                                   blocked=[f"{agent.name} failed: {exc}"]))
    proposed, blocked, needs = [], [], []
    for r in results:
        proposed.extend(r["proposed_changes"])
        blocked.extend(r["blocked"])
        needs.extend(r["needs_owner"])
    # De-duplicate needs_owner while keeping order.
    seen, needs_unique = set(), []
    for n in needs:
        if n not in seen:
            seen.add(n)
            needs_unique.append(n)
    source = None
    if isinstance(context, dict):
        source = context.get("context_source") or context.get("context_date")
    package = {
        "approved": False,
        "applied": False,
        "context_source": source,
        "context_note": "Snapshot only — re-check against the live store before any push.",
        "agents_run": len(results),
        "agent_results": results,
        "proposed_changes": proposed,
        "blocked": blocked,
        "needs_owner": needs_unique,
    }
    return package


def apply_package(package, approved=False):
    """Approval gate for code-level application.

    This function NEVER applies a package to Shopify, even when
    approved=True, because this codebase has no Shopify client and
    must not gain one silently. An approved package is pasted to Muse
    in chat, checked against the live store, and pushed there only
    after the owner approves the exact changes.
    """
    if not approved:
        raise PermissionError(
            "apply_package blocked: owner approval is required and was not given.")
    raise NotImplementedError(
        "Shopify writes are not done by this code. Paste the approved "
        "package to Muse in chat; Muse checks it against the live store "
        "and pushes only the exact changes the owner approved.")


def load_context(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the 36-agent GGOS swarm (report-only).")
    parser.add_argument("--context", required=True, help="JSON file with products (list or dict).")
    parser.add_argument("--db", default=None, help="Optional local audit DB path.")
    parser.add_argument("--out", default=None, help="Optional report JSON path.")
    args = parser.parse_args(argv)
    context = load_context(args.context)
    package = run_swarm(context, db_path=args.db)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(package, fh, indent=2)
    print(f"Agents run: {package['agents_run']}")
    print(f"Proposed changes (draft only): {len(package['proposed_changes'])}")
    print(f"Blocked items: {len(package['blocked'])}")
    print(f"Needs owner: {len(package['needs_owner'])}")
    print("Approved: False — Applied: False (approval gate: paste this package to Muse in chat)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
