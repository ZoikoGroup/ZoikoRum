--
-- PostgreSQL database dump
--

\restrict NhABbKmlu7wQMwYIUcrwzNQUArmUvOyOKWmJE0nMF2kKwtvEwqp4DWob1JNHb9n

-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: admin; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA admin;


--
-- Name: ai; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ai;


--
-- Name: analytics; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA analytics;


--
-- Name: audit; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA audit;


--
-- Name: buyer; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA buyer;


--
-- Name: contract; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA contract;


--
-- Name: dispute; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA dispute;


--
-- Name: escrow; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA escrow;


--
-- Name: firm; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA firm;


--
-- Name: identity; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA identity;


--
-- Name: marketplace; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA marketplace;


--
-- Name: messaging; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA messaging;


--
-- Name: notification; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA notification;


--
-- Name: payments; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA payments;


--
-- Name: platform; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA platform;


--
-- Name: policy; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA policy;


--
-- Name: professional; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA professional;


--
-- Name: proposal; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA proposal;


--
-- Name: review; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA review;


--
-- Name: search; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA search;


--
-- Name: trust; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA trust;


--
-- Name: verification; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA verification;


--
-- Name: guard_prompt(); Type: FUNCTION; Schema: ai; Owner: -
--

CREATE FUNCTION ai.guard_prompt() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR (OLD.status <> 'DRAFT' AND (NEW.prompt_key IS DISTINCT FROM OLD.prompt_key
             OR NEW.version IS DISTINCT FROM OLD.version OR NEW.instructions IS DISTINCT FROM OLD.instructions
             OR NEW.golden_tests IS DISTINCT FROM OLD.golden_tests OR NEW.target_model IS DISTINCT FROM OLD.target_model
             OR NEW.approved_by IS DISTINCT FROM OLD.approved_by OR NEW.status <> 'RETIRED')) THEN
             RAISE EXCEPTION 'approved prompt versions are immutable';
          END IF;
          RETURN NEW;
        END; $$;


--
-- Name: guard_change_order_history(); Type: FUNCTION; Schema: contract; Owner: -
--

CREATE FUNCTION contract.guard_change_order_history() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'change orders are append-only';
            END IF;
            IF OLD.contract_id IS DISTINCT FROM NEW.contract_id
               OR OLD.proposed_by_identity_id IS DISTINCT FROM NEW.proposed_by_identity_id
               OR OLD.proposer_party IS DISTINCT FROM NEW.proposer_party
               OR OLD.change_type IS DISTINCT FROM NEW.change_type
               OR OLD.delta IS DISTINCT FROM NEW.delta
               OR OLD.impact IS DISTINCT FROM NEW.impact
               OR OLD.base_contract_version IS DISTINCT FROM NEW.base_contract_version
               OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                RAISE EXCEPTION 'change order proposal details are immutable';
            END IF;
            IF OLD.status = 'PROPOSED' THEN
                IF NEW.status NOT IN ('APPROVED', 'REJECTED')
                   OR NEW.decided_by_identity_id IS NULL
                   OR NEW.decided_at IS NULL
                   OR (NEW.status = 'REJECTED' AND NEW.applied_version IS NOT NULL)
                   OR (NEW.applied_version IS NOT NULL AND NEW.applied_version <= NEW.base_contract_version) THEN
                    RAISE EXCEPTION 'invalid change order decision transition';
                END IF;
            ELSIF OLD.status = 'APPROVED' AND OLD.applied_version IS NULL THEN
                IF NEW.status <> 'APPROVED'
                   OR NEW.applied_version IS NULL
                   OR NEW.applied_version <= NEW.base_contract_version
                   OR NEW.decided_by_identity_id IS DISTINCT FROM OLD.decided_by_identity_id
                   OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
                   OR NEW.decision_reason IS DISTINCT FROM OLD.decision_reason THEN
                    RAISE EXCEPTION 'invalid change order execution transition';
                END IF;
            ELSE
                RAISE EXCEPTION 'change order decisions are final';
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: guard_appeal(); Type: FUNCTION; Schema: dispute; Owner: -
--

CREATE FUNCTION dispute.guard_appeal() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR OLD.status <> 'PENDING' OR NEW.case_id IS DISTINCT FROM OLD.case_id
            OR NEW.submitted_by IS DISTINCT FROM OLD.submitted_by OR NEW.grounds IS DISTINCT FROM OLD.grounds
            OR NEW.explanation IS DISTINCT FROM OLD.explanation OR NEW.evidence IS DISTINCT FROM OLD.evidence THEN
            RAISE EXCEPTION 'appeal submissions and issued decisions are immutable';
          END IF;
          RETURN NEW;
        END; $$;


--
-- Name: guard_decision(); Type: FUNCTION; Schema: dispute; Owner: -
--

CREATE FUNCTION dispute.guard_decision() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF OLD.decision IS NOT NULL AND NEW.decision IS DISTINCT FROM OLD.decision THEN
            RAISE EXCEPTION 'issued dispute decisions are immutable';
          END IF;
          RETURN NEW;
        END; $$;


--
-- Name: prevent_mutation(); Type: FUNCTION; Schema: platform; Owner: -
--

CREATE FUNCTION platform.prevent_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  RAISE EXCEPTION 'table %.% is append-only (% rejected)', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'insufficient_privilege';
END;
$$;


--
-- Name: prevent_mutation_except_name_erasure(); Type: FUNCTION; Schema: platform; Owner: -
--

CREATE FUNCTION platform.prevent_mutation_except_name_erasure() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF TG_OP = 'UPDATE'
     AND coalesce(current_setting('zoikorum.privacy_erasure', true), '') = 'on'
     AND (to_jsonb(NEW) ->> TG_ARGV[0]) = 'Deleted user'
     AND (to_jsonb(NEW) - TG_ARGV[0]) = (to_jsonb(OLD) - TG_ARGV[0]) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'table %.% is append-only (% rejected)', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'insufficient_privilege';
END;
$$;


--
-- Name: guard_active_version(); Type: FUNCTION; Schema: policy; Owner: -
--

CREATE FUNCTION policy.guard_active_version() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF TG_OP = 'DELETE' OR OLD.status = 'ACTIVE' THEN
    RAISE EXCEPTION 'active policy versions are immutable' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: enforcement_cases; Type: TABLE; Schema: admin; Owner: -
--

CREATE TABLE admin.enforcement_cases (
    subject_type character varying(30) NOT NULL,
    subject_id uuid NOT NULL,
    source_event_id uuid,
    signal_source character varying(100) NOT NULL,
    summary character varying(2000) NOT NULL,
    evidence_refs jsonb NOT NULL,
    level integer NOT NULL,
    reason_code character varying(100),
    status character varying(30) NOT NULL,
    action character varying(40),
    notice jsonb,
    opened_by uuid,
    proposed_by uuid,
    approvals jsonb NOT NULL,
    duration_days integer,
    expires_at timestamp with time zone,
    applied_at timestamp with time zone,
    reversed_by uuid,
    appeal jsonb,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL
);


--
-- Name: inference_logs; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.inference_logs (
    prompt_id uuid,
    prompt_version integer,
    model character varying(100) NOT NULL,
    input_sha256 character varying(64) NOT NULL,
    output text NOT NULL,
    purpose character varying(60) NOT NULL,
    subject_id uuid NOT NULL,
    requested_by uuid NOT NULL,
    latency_ms integer NOT NULL,
    fallback_used boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: prompt_versions; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.prompt_versions (
    prompt_key character varying(60) NOT NULL,
    version integer NOT NULL,
    owner uuid,
    target_model character varying(100) NOT NULL,
    instructions text NOT NULL,
    golden_tests jsonb NOT NULL,
    status character varying(20) NOT NULL,
    approved_by uuid,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: risk_observations; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.risk_observations (
    source_event_id uuid NOT NULL,
    identity_id uuid NOT NULL,
    kind character varying(40) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: event_facts; Type: TABLE; Schema: analytics; Owner: -
--

CREATE TABLE analytics.event_facts (
    source_event_id uuid NOT NULL,
    seq bigint NOT NULL,
    event_type character varying(200) NOT NULL,
    organization_id uuid,
    professional_id uuid,
    aggregate_id character varying(100) NOT NULL,
    payload jsonb NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: event_facts_seq_seq; Type: SEQUENCE; Schema: analytics; Owner: -
--

ALTER TABLE analytics.event_facts ALTER COLUMN seq ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME analytics.event_facts_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: audit_records; Type: TABLE; Schema: audit; Owner: -
--

CREATE TABLE audit.audit_records (
    seq bigint NOT NULL,
    source_event_id uuid NOT NULL,
    action character varying(200) NOT NULL,
    actor_id character varying(100),
    actor_type character varying(30) NOT NULL,
    auth_strength character varying(20),
    object_type character varying(100) NOT NULL,
    object_id character varying(100) NOT NULL,
    tenant_id character varying(100),
    correlation_id character varying(100) NOT NULL,
    causation_id character varying(100),
    policy_version character varying(100),
    evidence_hash character varying(64),
    details jsonb NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    prev_hash character varying(64) NOT NULL,
    hash character varying(64) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: audit_records_seq_seq; Type: SEQUENCE; Schema: audit; Owner: -
--

ALTER TABLE audit.audit_records ALTER COLUMN seq ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME audit.audit_records_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: export_jobs; Type: TABLE; Schema: audit; Owner: -
--

CREATE TABLE audit.export_jobs (
    requested_by uuid NOT NULL,
    scope jsonb NOT NULL,
    status character varying(20) NOT NULL,
    format character varying(10) NOT NULL,
    record_count bigint,
    content text,
    content_sha256 character varying(64),
    chain_head_hash character varying(64),
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: billing_contacts; Type: TABLE; Schema: buyer; Owner: -
--

CREATE TABLE buyer.billing_contacts (
    organization_id uuid NOT NULL,
    identity_id uuid NOT NULL,
    is_primary boolean NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: business_units; Type: TABLE; Schema: buyer; Owner: -
--

CREATE TABLE buyer.business_units (
    organization_id uuid NOT NULL,
    name character varying(150) NOT NULL,
    parent_id uuid,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: cost_centers; Type: TABLE; Schema: buyer; Owner: -
--

CREATE TABLE buyer.cost_centers (
    organization_id uuid NOT NULL,
    business_unit_id uuid,
    name character varying(150) NOT NULL,
    code character varying(50) NOT NULL,
    quarterly_budget_minor bigint,
    currency character varying(3),
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: invitations; Type: TABLE; Schema: buyer; Owner: -
--

CREATE TABLE buyer.invitations (
    organization_id uuid NOT NULL,
    email character varying(320) NOT NULL,
    roles character varying(40)[] NOT NULL,
    spend_limit_minor bigint,
    spend_limit_currency character varying(3),
    business_unit_id uuid,
    token_hash character varying(64) NOT NULL,
    status character varying(20) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    invited_by uuid NOT NULL,
    responded_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: members; Type: TABLE; Schema: buyer; Owner: -
--

CREATE TABLE buyer.members (
    organization_id uuid NOT NULL,
    identity_id uuid NOT NULL,
    email character varying(320) NOT NULL,
    display_name character varying(200) NOT NULL,
    roles character varying(40)[] NOT NULL,
    spend_limit_minor bigint,
    spend_limit_currency character varying(3),
    business_unit_id uuid,
    status character varying(20) NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: organizations; Type: TABLE; Schema: buyer; Owner: -
--

CREATE TABLE buyer.organizations (
    name character varying(200) NOT NULL,
    org_type character varying(20) NOT NULL,
    country character varying(2) NOT NULL,
    status character varying(20) NOT NULL,
    business_context character varying(30),
    created_by uuid NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL,
    industry character varying(80),
    time_zone character varying(64)
);


--
-- Name: change_orders; Type: TABLE; Schema: contract; Owner: -
--

CREATE TABLE contract.change_orders (
    id uuid NOT NULL,
    contract_id uuid NOT NULL,
    proposed_by_identity_id uuid NOT NULL,
    proposer_party character varying(20) NOT NULL,
    change_type character varying(30) NOT NULL,
    delta jsonb NOT NULL,
    impact character varying(1000) NOT NULL,
    base_contract_version integer NOT NULL,
    status character varying(20) NOT NULL,
    decided_by_identity_id uuid,
    decision_reason character varying(1000),
    decided_at timestamp with time zone,
    applied_version integer,
    version bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: contract_revisions; Type: TABLE; Schema: contract; Owner: -
--

CREATE TABLE contract.contract_revisions (
    id uuid NOT NULL,
    contract_id uuid NOT NULL,
    contract_version integer NOT NULL,
    change_order_id uuid,
    currency character varying(3) NOT NULL,
    total_minor bigint NOT NULL,
    terms jsonb NOT NULL,
    milestones jsonb NOT NULL,
    terms_hash character varying(64) NOT NULL,
    document text NOT NULL,
    document_sha256 character varying(64) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: contracts; Type: TABLE; Schema: contract; Owner: -
--

CREATE TABLE contract.contracts (
    reference character varying(20) NOT NULL,
    proposal_id uuid NOT NULL,
    request_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    buyer_identity_id uuid NOT NULL,
    professional_id uuid NOT NULL,
    firm_id uuid,
    title character varying(200) NOT NULL,
    engagement_type character varying(20) NOT NULL,
    pricing_model character varying(20),
    status character varying(30) NOT NULL,
    currency character varying(3) NOT NULL,
    total_minor bigint NOT NULL,
    terms jsonb NOT NULL,
    terms_hash character varying(64) NOT NULL,
    contract_version integer NOT NULL,
    parties jsonb NOT NULL,
    nda_required boolean NOT NULL,
    document text NOT NULL,
    document_sha256 character varying(64) NOT NULL,
    policy_version_label character varying(120) NOT NULL,
    signature_deadline timestamp with time zone NOT NULL,
    activated_at timestamp with time zone,
    completed_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL,
    pending_change_order_id uuid,
    policy_version_id uuid
);


--
-- Name: milestones; Type: TABLE; Schema: contract; Owner: -
--

CREATE TABLE contract.milestones (
    contract_id uuid NOT NULL,
    sequence integer NOT NULL,
    title character varying(200) NOT NULL,
    description character varying(1000) NOT NULL,
    amount_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    due_date date,
    deliverable_keys jsonb NOT NULL,
    status character varying(30) NOT NULL,
    started_at timestamp with time zone,
    submitted_at timestamp with time zone,
    acceptance_due_at timestamp with time zone,
    accepted_at timestamp with time zone,
    accepted_by uuid,
    revision_count integer NOT NULL,
    last_revision_reason character varying(1000),
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL,
    partial_offer_minor bigint,
    partial_offer_reason character varying(1000),
    partial_offered_at timestamp with time zone,
    accepted_release_minor bigint
);


--
-- Name: signatures; Type: TABLE; Schema: contract; Owner: -
--

CREATE TABLE contract.signatures (
    contract_id uuid NOT NULL,
    contract_version integer NOT NULL,
    party character varying(20) NOT NULL,
    signer_identity_id uuid NOT NULL,
    signer_name character varying(200) NOT NULL,
    terms_hash character varying(64) NOT NULL,
    auth_strength character varying(20) NOT NULL,
    ip character varying(64),
    signed_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: submissions; Type: TABLE; Schema: contract; Owner: -
--

CREATE TABLE contract.submissions (
    milestone_id uuid NOT NULL,
    submitted_by uuid NOT NULL,
    note character varying(2000) NOT NULL,
    files jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: appeals; Type: TABLE; Schema: dispute; Owner: -
--

CREATE TABLE dispute.appeals (
    case_id uuid NOT NULL,
    submitted_by uuid NOT NULL,
    grounds character varying(40) NOT NULL,
    explanation character varying(4000) NOT NULL,
    evidence jsonb NOT NULL,
    status character varying(20) NOT NULL,
    reviewed_by uuid,
    decision_reason character varying(4000),
    remediation character varying(4000),
    decided_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: cases; Type: TABLE; Schema: dispute; Owner: -
--

CREATE TABLE dispute.cases (
    reference character varying(20) NOT NULL,
    contract_id uuid NOT NULL,
    contract_reference character varying(20) NOT NULL,
    organization_id uuid NOT NULL,
    professional_id uuid NOT NULL,
    milestone_ids jsonb NOT NULL,
    category character varying(30) NOT NULL,
    summary character varying(300) NOT NULL,
    desired_outcome character varying(30) NOT NULL,
    context character varying(1000) NOT NULL,
    initiated_by uuid,
    initiator_party character varying(20) NOT NULL,
    status character varying(30) NOT NULL,
    currency character varying(3) NOT NULL,
    disputed_minor bigint NOT NULL,
    evidence_deadline timestamp with time zone NOT NULL,
    evidence_complete jsonb NOT NULL,
    direct_deadline timestamp with time zone,
    escalated_at timestamp with time zone,
    mediator_identity_id uuid,
    recommendation jsonb,
    pending_decision jsonb,
    decision jsonb,
    decided_at timestamp with time zone,
    closed_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL
);


--
-- Name: evidence_items; Type: TABLE; Schema: dispute; Owner: -
--

CREATE TABLE dispute.evidence_items (
    case_id uuid NOT NULL,
    party character varying(20) NOT NULL,
    submitted_by uuid NOT NULL,
    evidence_type character varying(30) NOT NULL,
    description character varying(1000) NOT NULL,
    items jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: resolution_proposals; Type: TABLE; Schema: dispute; Owner: -
--

CREATE TABLE dispute.resolution_proposals (
    case_id uuid NOT NULL,
    party character varying(20) NOT NULL,
    proposed_by uuid NOT NULL,
    outcome character varying(30) NOT NULL,
    allocations jsonb NOT NULL,
    note character varying(1000) NOT NULL,
    status character varying(20) NOT NULL,
    responded_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: timeline; Type: TABLE; Schema: dispute; Owner: -
--

CREATE TABLE dispute.timeline (
    case_id uuid NOT NULL,
    kind character varying(40) NOT NULL,
    actor character varying(200) NOT NULL,
    text character varying(500) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: accounts; Type: TABLE; Schema: escrow; Owner: -
--

CREATE TABLE escrow.accounts (
    contract_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    professional_id uuid NOT NULL,
    currency character varying(3) NOT NULL,
    total_minor bigint NOT NULL,
    status character varying(30) NOT NULL,
    funded_minor bigint NOT NULL,
    held_minor bigint NOT NULL,
    on_hold_minor bigint NOT NULL,
    released_minor bigint NOT NULL,
    refunded_minor bigint NOT NULL,
    fees_minor bigint NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL,
    fee_bps integer
);


--
-- Name: allocations; Type: TABLE; Schema: escrow; Owner: -
--

CREATE TABLE escrow.allocations (
    account_id uuid NOT NULL,
    milestone_id uuid NOT NULL,
    sequence integer NOT NULL,
    title character varying(200) NOT NULL,
    amount_minor bigint NOT NULL,
    state character varying(30) NOT NULL,
    funding_id uuid,
    released_minor bigint NOT NULL,
    fee_minor bigint NOT NULL,
    refunded_minor bigint NOT NULL,
    funded_at timestamp with time zone,
    released_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL
);


--
-- Name: fundings; Type: TABLE; Schema: escrow; Owner: -
--

CREATE TABLE escrow.fundings (
    account_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    requested_by uuid NOT NULL,
    milestone_ids jsonb NOT NULL,
    amount_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    status character varying(20) NOT NULL,
    failure_message character varying(300),
    captured_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ledger_entries; Type: TABLE; Schema: escrow; Owner: -
--

CREATE TABLE escrow.ledger_entries (
    entry_group_id uuid NOT NULL,
    account_id uuid NOT NULL,
    entry_type character varying(30) NOT NULL,
    ledger_account character varying(30) NOT NULL,
    debit_minor bigint NOT NULL,
    credit_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    reference_type character varying(30) NOT NULL,
    reference_id uuid NOT NULL,
    milestone_id uuid,
    memo character varying(200) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: releases; Type: TABLE; Schema: escrow; Owner: -
--

CREATE TABLE escrow.releases (
    account_id uuid NOT NULL,
    milestone_id uuid NOT NULL,
    gross_minor bigint NOT NULL,
    fee_minor bigint NOT NULL,
    net_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    fee_bps integer NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: firms; Type: TABLE; Schema: firm; Owner: -
--

CREATE TABLE firm.firms (
    legal_name character varying(200) NOT NULL,
    trading_name character varying(200),
    registration_number character varying(100),
    hq_country character varying(2) NOT NULL,
    size_band character varying(10),
    primary_category character varying(100),
    website character varying(300),
    status character varying(30) NOT NULL,
    created_by uuid NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL
);


--
-- Name: invitations; Type: TABLE; Schema: firm; Owner: -
--

CREATE TABLE firm.invitations (
    firm_id uuid NOT NULL,
    email character varying(320) NOT NULL,
    roles character varying(40)[] NOT NULL,
    token_hash character varying(64) NOT NULL,
    status character varying(20) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    invited_by uuid NOT NULL,
    responded_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: members; Type: TABLE; Schema: firm; Owner: -
--

CREATE TABLE firm.members (
    firm_id uuid NOT NULL,
    identity_id uuid NOT NULL,
    email character varying(320) NOT NULL,
    display_name character varying(200) NOT NULL,
    roles character varying(40)[] NOT NULL,
    status character varying(20) NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: consent_records; Type: TABLE; Schema: identity; Owner: -
--

CREATE TABLE identity.consent_records (
    identity_id uuid NOT NULL,
    consent_type character varying(50) NOT NULL,
    document_version character varying(50) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: data_requests; Type: TABLE; Schema: identity; Owner: -
--

CREATE TABLE identity.data_requests (
    identity_id uuid NOT NULL,
    request_type character varying(20) NOT NULL,
    status character varying(20) NOT NULL,
    completed_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    scheduled_for timestamp with time zone,
    expires_at timestamp with time zone,
    export_key character varying(300),
    detail jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: duplicate_suspicions; Type: TABLE; Schema: identity; Owner: -
--

CREATE TABLE identity.duplicate_suspicions (
    identity_id uuid NOT NULL,
    other_identity_id uuid NOT NULL,
    signal character varying(40) NOT NULL,
    status character varying(20) NOT NULL,
    user_answer character varying(20),
    user_note character varying(500),
    resolved_by uuid,
    resolved_at timestamp with time zone,
    resolution_note character varying(500),
    kept_identity_id uuid,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: identities; Type: TABLE; Schema: identity; Owner: -
--

CREATE TABLE identity.identities (
    email character varying(320) NOT NULL,
    email_confirmed_at timestamp with time zone,
    password_hash character varying(255),
    display_name character varying(200) NOT NULL,
    country character varying(2) NOT NULL,
    status character varying(20) NOT NULL,
    platform_roles character varying(50)[] NOT NULL,
    personas character varying(30)[] NOT NULL,
    primary_persona character varying(30),
    signup_organization_name character varying(200),
    mfa_secret_enc character varying(500),
    mfa_enabled_at timestamp with time zone,
    failed_login_count integer NOT NULL,
    locked_until timestamp with time zone,
    enterprise_federated boolean NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL,
    phone_enc character varying(500),
    language character varying(10) DEFAULT 'en'::character varying NOT NULL,
    time_zone character varying(64),
    confirmation_requested_at timestamp with time zone,
    mfa_recovery_hashes jsonb
);


--
-- Name: identity_links; Type: TABLE; Schema: identity; Owner: -
--

CREATE TABLE identity.identity_links (
    identity_id uuid NOT NULL,
    link_type character varying(30) NOT NULL,
    target_id uuid NOT NULL,
    roles character varying(50)[] NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    target_kind character varying(20)
);


--
-- Name: sessions; Type: TABLE; Schema: identity; Owner: -
--

CREATE TABLE identity.sessions (
    identity_id uuid NOT NULL,
    family_id uuid NOT NULL,
    refresh_token_hash character varying(64) NOT NULL,
    auth_strength character varying(20) NOT NULL,
    auth_time timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    rotated_at timestamp with time zone,
    revoked_at timestamp with time zone,
    user_agent character varying(500),
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: collection_items; Type: TABLE; Schema: marketplace; Owner: -
--

CREATE TABLE marketplace.collection_items (
    collection_id uuid NOT NULL,
    professional_id uuid NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: collections; Type: TABLE; Schema: marketplace; Owner: -
--

CREATE TABLE marketplace.collections (
    identity_id uuid NOT NULL,
    name character varying(80) NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: saved_professionals; Type: TABLE; Schema: marketplace; Owner: -
--

CREATE TABLE marketplace.saved_professionals (
    identity_id uuid NOT NULL,
    professional_id uuid NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: saved_searches; Type: TABLE; Schema: marketplace; Owner: -
--

CREATE TABLE marketplace.saved_searches (
    identity_id uuid NOT NULL,
    name character varying(80) NOT NULL,
    params jsonb NOT NULL,
    last_viewed_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: specialization_suggestions; Type: TABLE; Schema: marketplace; Owner: -
--

CREATE TABLE marketplace.specialization_suggestions (
    identity_id uuid NOT NULL,
    professional_id uuid,
    text character varying(1000) NOT NULL,
    name character varying(200) NOT NULL,
    category_slug character varying(120),
    group_slug character varying(120),
    description character varying(500) NOT NULL,
    credential_likely boolean NOT NULL,
    source character varying(80) NOT NULL,
    status character varying(20) NOT NULL,
    resolved_slug character varying(120),
    resolved_by uuid,
    resolved_at timestamp with time zone,
    resolution_note character varying(500),
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: taxonomy_nodes; Type: TABLE; Schema: marketplace; Owner: -
--

CREATE TABLE marketplace.taxonomy_nodes (
    slug character varying(120) NOT NULL,
    name character varying(200) NOT NULL,
    level character varying(20) NOT NULL,
    parent_id uuid,
    category_slug character varying(120) NOT NULL,
    sort_order integer NOT NULL,
    requires_credential boolean NOT NULL,
    regulated boolean NOT NULL,
    deliverable_templates character varying(200)[] NOT NULL,
    credential_hints character varying(40)[] NOT NULL,
    status character varying(20) NOT NULL,
    taxonomy_version integer NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    requires_insurance boolean DEFAULT false NOT NULL
);


--
-- Name: attachments; Type: TABLE; Schema: messaging; Owner: -
--

CREATE TABLE messaging.attachments (
    thread_id uuid NOT NULL,
    uploaded_by uuid NOT NULL,
    name character varying(255) NOT NULL,
    content_type character varying(120) NOT NULL,
    size_bytes bigint NOT NULL,
    sha256 character varying(64) NOT NULL,
    storage_key character varying(500) NOT NULL,
    file_version integer NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: dispute_contexts; Type: TABLE; Schema: messaging; Owner: -
--

CREATE TABLE messaging.dispute_contexts (
    dispute_id uuid NOT NULL,
    contract_id uuid NOT NULL,
    category character varying(80) NOT NULL,
    initiated_by_identity_id uuid,
    is_open boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: messages; Type: TABLE; Schema: messaging; Owner: -
--

CREATE TABLE messaging.messages (
    thread_id uuid NOT NULL,
    sequence integer NOT NULL,
    sender_identity_id uuid,
    sender_name character varying(200) NOT NULL,
    body text NOT NULL,
    attachment_ids jsonb NOT NULL,
    content_hash character varying(64) NOT NULL,
    source_event_id uuid,
    flags jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: read_positions; Type: TABLE; Schema: messaging; Owner: -
--

CREATE TABLE messaging.read_positions (
    thread_id uuid NOT NULL,
    identity_id uuid NOT NULL,
    sequence integer NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: threads; Type: TABLE; Schema: messaging; Owner: -
--

CREATE TABLE messaging.threads (
    context_type character varying(30) NOT NULL,
    context_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    professional_id uuid NOT NULL,
    title character varying(250) NOT NULL,
    sequence integer NOT NULL,
    locked boolean NOT NULL,
    lock_reason character varying(300),
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: delivery_attempts; Type: TABLE; Schema: notification; Owner: -
--

CREATE TABLE notification.delivery_attempts (
    delivery_id uuid NOT NULL,
    response_status integer,
    error character varying(300),
    attempt integer NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: notifications; Type: TABLE; Schema: notification; Owner: -
--

CREATE TABLE notification.notifications (
    source_event_id uuid NOT NULL,
    identity_id uuid NOT NULL,
    event_type character varying(160) NOT NULL,
    title character varying(200) NOT NULL,
    body text NOT NULL,
    url character varying(500) NOT NULL,
    notice jsonb,
    in_app boolean NOT NULL,
    mandatory boolean NOT NULL,
    read_at timestamp with time zone,
    email_status character varying(20) NOT NULL,
    email_attempts integer NOT NULL,
    delivered_at timestamp with time zone,
    last_error character varying(300),
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: preferences; Type: TABLE; Schema: notification; Owner: -
--

CREATE TABLE notification.preferences (
    identity_id uuid NOT NULL,
    email boolean NOT NULL,
    in_app boolean NOT NULL,
    sms boolean NOT NULL,
    marketing boolean NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: webhook_deliveries; Type: TABLE; Schema: notification; Owner: -
--

CREATE TABLE notification.webhook_deliveries (
    endpoint_id uuid NOT NULL,
    source_event_id uuid NOT NULL,
    body jsonb NOT NULL,
    status character varying(20) NOT NULL,
    attempts integer NOT NULL,
    retry_until timestamp with time zone NOT NULL,
    delivered_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: webhook_endpoints; Type: TABLE; Schema: notification; Owner: -
--

CREATE TABLE notification.webhook_endpoints (
    organization_id uuid NOT NULL,
    url character varying(2000) NOT NULL,
    secret_encrypted text NOT NULL,
    event_types jsonb NOT NULL,
    enabled boolean NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: invoice_number_seq; Type: SEQUENCE; Schema: payments; Owner: -
--

CREATE SEQUENCE payments.invoice_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: invoices; Type: TABLE; Schema: payments; Owner: -
--

CREATE TABLE payments.invoices (
    number character varying(30) NOT NULL,
    release_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    contract_id uuid NOT NULL,
    milestone_id uuid,
    lines jsonb NOT NULL,
    tax_minor bigint NOT NULL,
    total_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    issued_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: payment_intents; Type: TABLE; Schema: payments; Owner: -
--

CREATE TABLE payments.payment_intents (
    funding_id uuid NOT NULL,
    escrow_account_id uuid NOT NULL,
    contract_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    amount_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    status character varying(20) NOT NULL,
    provider character varying(30) NOT NULL,
    provider_ref character varying(100),
    method_label character varying(80) NOT NULL,
    failure_code character varying(60),
    failure_message character varying(300),
    captured_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    charged_back_at timestamp with time zone,
    chargeback_minor bigint,
    chargeback_reason character varying(200)
);


--
-- Name: payout_accounts; Type: TABLE; Schema: payments; Owner: -
--

CREATE TABLE payments.payout_accounts (
    professional_id uuid NOT NULL,
    holder_name character varying(200) NOT NULL,
    country character varying(2) NOT NULL,
    currency character varying(3) NOT NULL,
    last4 character varying(4) NOT NULL,
    provider character varying(30) NOT NULL,
    provider_account_ref character varying(100) NOT NULL,
    status character varying(20) NOT NULL,
    created_by uuid NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: payouts; Type: TABLE; Schema: payments; Owner: -
--

CREATE TABLE payments.payouts (
    release_id uuid NOT NULL,
    professional_id uuid NOT NULL,
    contract_id uuid NOT NULL,
    milestone_id uuid,
    gross_minor bigint NOT NULL,
    fee_minor bigint NOT NULL,
    amount_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    status character varying(20) NOT NULL,
    provider_ref character varying(100),
    failure_message character varying(300),
    settled_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expected_at timestamp with time zone,
    transfer_ref character varying(100),
    provider_attempt integer NOT NULL
);


--
-- Name: reconciliation_batches; Type: TABLE; Schema: payments; Owner: -
--

CREATE TABLE payments.reconciliation_batches (
    day date NOT NULL,
    status character varying(20) NOT NULL,
    checks jsonb NOT NULL,
    mismatches bigint NOT NULL,
    run_by character varying(60) NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: refunds; Type: TABLE; Schema: payments; Owner: -
--

CREATE TABLE payments.refunds (
    escrow_refund_id uuid NOT NULL,
    payment_intent_id uuid,
    organization_id uuid NOT NULL,
    contract_id uuid NOT NULL,
    milestone_id uuid,
    dispute_id uuid,
    amount_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    status character varying(20) NOT NULL,
    provider_ref character varying(100),
    settled_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: webhook_events; Type: TABLE; Schema: payments; Owner: -
--

CREATE TABLE payments.webhook_events (
    provider character varying(30) NOT NULL,
    event_id character varying(120) NOT NULL,
    event_type character varying(80) NOT NULL,
    payload jsonb NOT NULL,
    outcome character varying(200) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alembic_version; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: consumer_failures; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.consumer_failures (
    consumer character varying(150) NOT NULL,
    event_id uuid NOT NULL,
    event_type character varying(200) NOT NULL,
    envelope jsonb NOT NULL,
    attempts integer NOT NULL,
    last_error text,
    status character varying(20) NOT NULL,
    financial boolean NOT NULL,
    next_attempt_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: idempotency_keys; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.idempotency_keys (
    scope character varying(300) NOT NULL,
    request_hash character varying(64) NOT NULL,
    response_status integer NOT NULL,
    response_body jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: inbox; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.inbox (
    id bigint NOT NULL,
    consumer character varying(150) NOT NULL,
    event_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: inbox_id_seq; Type: SEQUENCE; Schema: platform; Owner: -
--

ALTER TABLE platform.inbox ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME platform.inbox_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: outbox; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.outbox (
    seq bigint NOT NULL,
    event_id uuid NOT NULL,
    event_type character varying(200) NOT NULL,
    aggregate_type character varying(100) NOT NULL,
    aggregate_id character varying(100) NOT NULL,
    tenant_id character varying(100),
    envelope jsonb NOT NULL,
    published_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: outbox_seq_seq; Type: SEQUENCE; Schema: platform; Owner: -
--

ALTER TABLE platform.outbox ALTER COLUMN seq ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME platform.outbox_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: timers; Type: TABLE; Schema: platform; Owner: -
--

CREATE TABLE platform.timers (
    kind character varying(100) NOT NULL,
    key character varying(200) NOT NULL,
    fire_at timestamp with time zone NOT NULL,
    payload jsonb NOT NULL,
    fired_at timestamp with time zone,
    cancelled_at timestamp with time zone,
    attempts integer NOT NULL,
    last_error text,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: approval_requests; Type: TABLE; Schema: policy; Owner: -
--

CREATE TABLE policy.approval_requests (
    organization_id uuid NOT NULL,
    policy_version_id uuid,
    subject_type character varying(60) NOT NULL,
    subject_id uuid NOT NULL,
    action character varying(40) NOT NULL,
    requester_identity_id uuid,
    context_hash character varying(64) NOT NULL,
    request_key character varying(64) NOT NULL,
    attributes jsonb NOT NULL,
    workflows jsonb NOT NULL,
    reasons jsonb NOT NULL,
    status character varying(15) NOT NULL,
    deadline timestamp with time zone NOT NULL,
    escalation_role character varying(30) NOT NULL,
    escalation_count integer NOT NULL,
    step_up_required boolean NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL
);


--
-- Name: approval_votes; Type: TABLE; Schema: policy; Owner: -
--

CREATE TABLE policy.approval_votes (
    request_id uuid NOT NULL,
    step_id character varying(100) NOT NULL,
    identity_id uuid NOT NULL,
    authority_role character varying(30) NOT NULL,
    decision character varying(10) NOT NULL,
    reason character varying(1000) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: exception_requests; Type: TABLE; Schema: policy; Owner: -
--

CREATE TABLE policy.exception_requests (
    organization_id uuid NOT NULL,
    policy_version_id uuid,
    subject_type character varying(60) NOT NULL,
    subject_id uuid NOT NULL,
    action character varying(40) NOT NULL,
    context_hash character varying(64) NOT NULL,
    requester_identity_id uuid NOT NULL,
    justification text NOT NULL,
    documents jsonb NOT NULL,
    status character varying(15) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    decided_by uuid,
    decision_reason character varying(1000),
    decided_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL
);


--
-- Name: policy_evaluations; Type: TABLE; Schema: policy; Owner: -
--

CREATE TABLE policy.policy_evaluations (
    organization_id uuid,
    policy_version_id uuid,
    policy_profile_id uuid,
    policy_version_label character varying(120) NOT NULL,
    subject_type character varying(60) NOT NULL,
    subject_id uuid NOT NULL,
    action character varying(40) NOT NULL,
    actor_identity_id uuid,
    attributes jsonb NOT NULL,
    context_hash character varying(64) NOT NULL,
    decision character varying(25) NOT NULL,
    reasons jsonb NOT NULL,
    dry_run boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: profiles; Type: TABLE; Schema: policy; Owner: -
--

CREATE TABLE policy.profiles (
    organization_id uuid NOT NULL,
    name character varying(80) NOT NULL,
    description character varying(1000) NOT NULL,
    risk_level character varying(10) NOT NULL,
    business_unit_ids jsonb NOT NULL,
    active_version_id uuid,
    draft_version_id uuid,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL
);


--
-- Name: versions; Type: TABLE; Schema: policy; Owner: -
--

CREATE TABLE policy.versions (
    profile_id uuid NOT NULL,
    number integer NOT NULL,
    status character varying(10) NOT NULL,
    settings jsonb NOT NULL,
    rules jsonb NOT NULL,
    created_by uuid NOT NULL,
    activated_by uuid,
    activated_at timestamp with time zone,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: credential_claims; Type: TABLE; Schema: professional; Owner: -
--

CREATE TABLE professional.credential_claims (
    professional_id uuid NOT NULL,
    credential_type character varying(20) NOT NULL,
    name character varying(150) NOT NULL,
    issuing_body character varying(200) NOT NULL,
    registration_number character varying(100),
    jurisdiction character varying(10),
    issued_on date,
    expires_on date,
    specialization character varying(120),
    status character varying(20) NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: offerings; Type: TABLE; Schema: professional; Owner: -
--

CREATE TABLE professional.offerings (
    professional_id uuid NOT NULL,
    title character varying(150) NOT NULL,
    specialization character varying(120) NOT NULL,
    summary text,
    deliverables character varying(200)[] NOT NULL,
    engagement_types character varying(20)[] NOT NULL,
    pricing_model character varying(20) NOT NULL,
    starting_price_minor bigint,
    currency character varying(3),
    typical_duration character varying(50),
    status character varying(20) NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL
);


--
-- Name: professionals; Type: TABLE; Schema: professional; Owner: -
--

CREATE TABLE professional.professionals (
    identity_id uuid NOT NULL,
    firm_id uuid,
    status character varying(20) NOT NULL,
    display_name character varying(200) NOT NULL,
    legal_name character varying(200),
    headline character varying(120),
    years_experience_band character varying(10),
    bio text,
    languages character varying(40)[] NOT NULL,
    country character varying(2) NOT NULL,
    city character varying(100),
    website character varying(300),
    primary_category character varying(120),
    primary_specialization character varying(120),
    secondary_specializations character varying(120)[] NOT NULL,
    engagement_types character varying(20)[] NOT NULL,
    delivery_modes character varying(20)[] NOT NULL,
    pricing_models character varying(20)[] NOT NULL,
    rate_minor bigint,
    rate_currency character varying(3),
    rate_unit character varying(10),
    availability character varying(20) NOT NULL,
    max_concurrent_engagements integer,
    temporarily_unavailable boolean NOT NULL,
    active_engagements integer NOT NULL,
    served_jurisdictions character varying(2)[] NOT NULL,
    licensed_jurisdictions character varying(2)[] NOT NULL,
    cross_border_acknowledged_at timestamp with time zone,
    accuracy_attested_at timestamp with time zone,
    published_at timestamp with time zone,
    visibility_reduced boolean NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL,
    photo_key character varying(200),
    photo_content_type character varying(30),
    photo_sha256 character varying(64),
    weekly_hours integer
);


--
-- Name: saved_buyers; Type: TABLE; Schema: professional; Owner: -
--

CREATE TABLE professional.saved_buyers (
    professional_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    note character varying(500),
    alerts boolean NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: proposals; Type: TABLE; Schema: proposal; Owner: -
--

CREATE TABLE proposal.proposals (
    request_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    buyer_identity_id uuid NOT NULL,
    professional_id uuid NOT NULL,
    status character varying(20) NOT NULL,
    summary character varying(500) NOT NULL,
    scope_alignment character varying(20) NOT NULL,
    scope_notes character varying(1000),
    deliverables jsonb NOT NULL,
    milestones jsonb NOT NULL,
    pricing_model character varying(20) NOT NULL,
    total_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    start_date date,
    end_date date,
    assumptions jsonb NOT NULL,
    exclusions jsonb NOT NULL,
    valid_until date,
    revision_requests jsonb NOT NULL,
    revision_count integer NOT NULL,
    submitted_at timestamp with time zone,
    decided_at timestamp with time zone,
    decided_by uuid,
    reason_code character varying(60),
    reason_note character varying(500),
    terms_hash character varying(64),
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL,
    attachments jsonb DEFAULT '[]'::jsonb NOT NULL,
    policy_version_id uuid
);


--
-- Name: requests; Type: TABLE; Schema: proposal; Owner: -
--

CREATE TABLE proposal.requests (
    organization_id uuid NOT NULL,
    buyer_identity_id uuid NOT NULL,
    professional_id uuid NOT NULL,
    offering_id uuid,
    group_id uuid NOT NULL,
    service character varying(200) NOT NULL,
    specialization character varying(120),
    engagement_type character varying(20) NOT NULL,
    business_context character varying(20),
    objective character varying(300) NOT NULL,
    details character varying(1200) NOT NULL,
    desired_start_date date NOT NULL,
    estimated_duration character varying(20) NOT NULL,
    budget_min_minor bigint,
    budget_max_minor bigint,
    budget_currency character varying(3),
    delivery_mode character varying(10) NOT NULL,
    location character varying(200),
    nda_required boolean NOT NULL,
    nda_accepted_at timestamp with time zone,
    attachments jsonb NOT NULL,
    status character varying(20) NOT NULL,
    sent_at timestamp with time zone,
    closed_at timestamp with time zone,
    reason_code character varying(60),
    reason_note character varying(500),
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL,
    deliverables jsonb DEFAULT '[]'::jsonb NOT NULL,
    dependencies jsonb DEFAULT '[]'::jsonb NOT NULL,
    pricing_preferences jsonb DEFAULT '[]'::jsonb NOT NULL,
    payment_cadence character varying(20),
    cost_center_id uuid
);


--
-- Name: reviews; Type: TABLE; Schema: review; Owner: -
--

CREATE TABLE review.reviews (
    contract_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    professional_id uuid NOT NULL,
    reviewer_identity_id uuid NOT NULL,
    reviewer_name character varying(200) NOT NULL,
    organization_name character varying(200) NOT NULL,
    rating integer NOT NULL,
    comment character varying(2000) NOT NULL,
    engagement_reference character varying(40) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: professional_documents; Type: TABLE; Schema: search; Owner: -
--

CREATE TABLE search.professional_documents (
    professional_id uuid NOT NULL,
    visible boolean NOT NULL,
    visibility_reduced boolean NOT NULL,
    display_name character varying(200) NOT NULL,
    headline character varying(120),
    country character varying(2) NOT NULL,
    city character varying(100),
    years_experience_band character varying(10),
    languages character varying(40)[] NOT NULL,
    categories character varying(120)[] NOT NULL,
    primary_specialization character varying(120),
    specializations character varying(120)[] NOT NULL,
    specialization_names jsonb NOT NULL,
    engagement_types character varying(20)[] NOT NULL,
    delivery_modes character varying(20)[] NOT NULL,
    pricing_models character varying(20)[] NOT NULL,
    availability character varying(20) NOT NULL,
    served_jurisdictions character varying(2)[] NOT NULL,
    licensed_jurisdictions character varying(2)[] NOT NULL,
    tier character varying(1) NOT NULL,
    trust_score integer NOT NULL,
    dimensions jsonb NOT NULL,
    verified_credentials character varying(200)[] NOT NULL,
    offering_titles character varying(150)[] NOT NULL,
    starting_price_minor bigint,
    price_currency character varying(3),
    bio_excerpt text,
    published_at timestamp with time zone,
    last_event_at timestamp with time zone,
    document tsvector NOT NULL,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    verified_jurisdictions character varying(2)[] DEFAULT '{}'::character varying[] NOT NULL,
    photo_url character varying(200),
    completed_engagements integer DEFAULT 0 NOT NULL,
    milestones_due integer DEFAULT 0 NOT NULL,
    milestones_on_time integer DEFAULT 0 NOT NULL,
    review_count integer DEFAULT 0 NOT NULL,
    review_average double precision,
    response_median_hours double precision
);


--
-- Name: profiles; Type: TABLE; Schema: trust; Owner: -
--

CREATE TABLE trust.profiles (
    professional_id uuid NOT NULL,
    tier character varying(1) NOT NULL,
    score integer NOT NULL,
    dimensions jsonb NOT NULL,
    explanation jsonb NOT NULL,
    flags character varying(60)[] NOT NULL,
    engagement_suspended boolean NOT NULL,
    recomputed_at timestamp with time zone,
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: signals; Type: TABLE; Schema: trust; Owner: -
--

CREATE TABLE trust.signals (
    professional_id uuid NOT NULL,
    source_event_id uuid NOT NULL,
    source_event_type character varying(120) NOT NULL,
    signal_type character varying(30) NOT NULL,
    adverse boolean NOT NULL,
    summary character varying(300) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tier_history; Type: TABLE; Schema: trust; Owner: -
--

CREATE TABLE trust.tier_history (
    professional_id uuid NOT NULL,
    from_tier character varying(1) NOT NULL,
    to_tier character varying(1) NOT NULL,
    reasons jsonb NOT NULL,
    source_event_type character varying(120) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: appeals; Type: TABLE; Schema: verification; Owner: -
--

CREATE TABLE verification.appeals (
    case_id uuid NOT NULL,
    filed_by uuid NOT NULL,
    statement character varying(2000) NOT NULL,
    case_status_at_filing character varying(20) NOT NULL,
    original_reviewer_id uuid,
    status character varying(20) NOT NULL,
    decided_by uuid,
    decided_at timestamp with time zone,
    decision_note character varying(1000),
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: cases; Type: TABLE; Schema: verification; Owner: -
--

CREATE TABLE verification.cases (
    subject_type character varying(20) NOT NULL,
    subject_id uuid NOT NULL,
    owner_identity_id uuid NOT NULL,
    verification_type character varying(30) NOT NULL,
    status character varying(20) NOT NULL,
    label character varying(200) NOT NULL,
    jurisdiction character varying(10),
    credential_claim_id uuid,
    specialization character varying(120),
    details jsonb NOT NULL,
    provider_result character varying(20),
    estimated_completion timestamp with time zone,
    reviewer_id uuid,
    decided_at timestamp with time zone,
    verified_at timestamp with time zone,
    expires_at timestamp with time zone,
    reason_code character varying(60),
    public_reason character varying(500),
    id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version bigint NOT NULL
);


--
-- Name: evidence_checks; Type: TABLE; Schema: verification; Owner: -
--

CREATE TABLE verification.evidence_checks (
    evidence_id uuid NOT NULL,
    case_id uuid NOT NULL,
    verdict character varying(20) NOT NULL,
    seen character varying(120),
    note character varying(300) NOT NULL,
    source character varying(100) NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: evidence_items; Type: TABLE; Schema: verification; Owner: -
--

CREATE TABLE verification.evidence_items (
    case_id uuid NOT NULL,
    evidence_type character varying(40) NOT NULL,
    file_name character varying(255) NOT NULL,
    sha256 character varying(64) NOT NULL,
    size_bytes bigint NOT NULL,
    storage_key character varying(500),
    uploaded_by uuid NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    content_type character varying(100),
    storage_version character varying(200)
);


--
-- Name: provider_events; Type: TABLE; Schema: verification; Owner: -
--

CREATE TABLE verification.provider_events (
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    event_id character varying(120) NOT NULL,
    event_type character varying(100) NOT NULL,
    payload_sha256 character varying(64) NOT NULL
);


--
-- Name: provider_sessions; Type: TABLE; Schema: verification; Owner: -
--

CREATE TABLE verification.provider_sessions (
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    case_id uuid NOT NULL,
    provider_ref character varying(120) NOT NULL,
    status character varying(30) NOT NULL,
    provider character varying(20),
    hosted_url character varying(1000),
    reason character varying(300)
);


--
-- Data for Name: enforcement_cases; Type: TABLE DATA; Schema: admin; Owner: -
--

COPY admin.enforcement_cases (subject_type, subject_id, source_event_id, signal_source, summary, evidence_refs, level, reason_code, status, action, notice, opened_by, proposed_by, approvals, duration_days, expires_at, applied_at, reversed_by, appeal, id, updated_at, created_at, version) FROM stdin;
\.


--
-- Data for Name: inference_logs; Type: TABLE DATA; Schema: ai; Owner: -
--

COPY ai.inference_logs (prompt_id, prompt_version, model, input_sha256, output, purpose, subject_id, requested_by, latency_ms, fallback_used, id, created_at) FROM stdin;
\.


--
-- Data for Name: prompt_versions; Type: TABLE DATA; Schema: ai; Owner: -
--

COPY ai.prompt_versions (prompt_key, version, owner, target_model, instructions, golden_tests, status, approved_by, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: risk_observations; Type: TABLE DATA; Schema: ai; Owner: -
--

COPY ai.risk_observations (source_event_id, identity_id, kind, id, created_at) FROM stdin;
\.


--
-- Data for Name: event_facts; Type: TABLE DATA; Schema: analytics; Owner: -
--

COPY analytics.event_facts (source_event_id, seq, event_type, organization_id, professional_id, aggregate_id, payload, occurred_at, id, created_at) FROM stdin;
\.


--
-- Data for Name: audit_records; Type: TABLE DATA; Schema: audit; Owner: -
--

COPY audit.audit_records (seq, source_event_id, action, actor_id, actor_type, auth_strength, object_type, object_id, tenant_id, correlation_id, causation_id, policy_version, evidence_hash, details, occurred_at, prev_hash, hash, id, created_at) FROM stdin;
\.


--
-- Data for Name: export_jobs; Type: TABLE DATA; Schema: audit; Owner: -
--

COPY audit.export_jobs (requested_by, scope, status, format, record_count, content, content_sha256, chain_head_hash, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: billing_contacts; Type: TABLE DATA; Schema: buyer; Owner: -
--

COPY buyer.billing_contacts (organization_id, identity_id, is_primary, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: business_units; Type: TABLE DATA; Schema: buyer; Owner: -
--

COPY buyer.business_units (organization_id, name, parent_id, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: cost_centers; Type: TABLE DATA; Schema: buyer; Owner: -
--

COPY buyer.cost_centers (organization_id, business_unit_id, name, code, quarterly_budget_minor, currency, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: invitations; Type: TABLE DATA; Schema: buyer; Owner: -
--

COPY buyer.invitations (organization_id, email, roles, spend_limit_minor, spend_limit_currency, business_unit_id, token_hash, status, expires_at, invited_by, responded_at, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: members; Type: TABLE DATA; Schema: buyer; Owner: -
--

COPY buyer.members (organization_id, identity_id, email, display_name, roles, spend_limit_minor, spend_limit_currency, business_unit_id, status, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: organizations; Type: TABLE DATA; Schema: buyer; Owner: -
--

COPY buyer.organizations (name, org_type, country, status, business_context, created_by, id, updated_at, created_at, version, industry, time_zone) FROM stdin;
\.


--
-- Data for Name: change_orders; Type: TABLE DATA; Schema: contract; Owner: -
--

COPY contract.change_orders (id, contract_id, proposed_by_identity_id, proposer_party, change_type, delta, impact, base_contract_version, status, decided_by_identity_id, decision_reason, decided_at, applied_version, version, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: contract_revisions; Type: TABLE DATA; Schema: contract; Owner: -
--

COPY contract.contract_revisions (id, contract_id, contract_version, change_order_id, currency, total_minor, terms, milestones, terms_hash, document, document_sha256, created_at) FROM stdin;
\.


--
-- Data for Name: contracts; Type: TABLE DATA; Schema: contract; Owner: -
--

COPY contract.contracts (reference, proposal_id, request_id, organization_id, buyer_identity_id, professional_id, firm_id, title, engagement_type, pricing_model, status, currency, total_minor, terms, terms_hash, contract_version, parties, nda_required, document, document_sha256, policy_version_label, signature_deadline, activated_at, completed_at, id, updated_at, created_at, version, pending_change_order_id, policy_version_id) FROM stdin;
\.


--
-- Data for Name: milestones; Type: TABLE DATA; Schema: contract; Owner: -
--

COPY contract.milestones (contract_id, sequence, title, description, amount_minor, currency, due_date, deliverable_keys, status, started_at, submitted_at, acceptance_due_at, accepted_at, accepted_by, revision_count, last_revision_reason, id, updated_at, created_at, version, partial_offer_minor, partial_offer_reason, partial_offered_at, accepted_release_minor) FROM stdin;
\.


--
-- Data for Name: signatures; Type: TABLE DATA; Schema: contract; Owner: -
--

COPY contract.signatures (contract_id, contract_version, party, signer_identity_id, signer_name, terms_hash, auth_strength, ip, signed_at, id, created_at) FROM stdin;
\.


--
-- Data for Name: submissions; Type: TABLE DATA; Schema: contract; Owner: -
--

COPY contract.submissions (milestone_id, submitted_by, note, files, id, created_at) FROM stdin;
\.


--
-- Data for Name: appeals; Type: TABLE DATA; Schema: dispute; Owner: -
--

COPY dispute.appeals (case_id, submitted_by, grounds, explanation, evidence, status, reviewed_by, decision_reason, remediation, decided_at, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: cases; Type: TABLE DATA; Schema: dispute; Owner: -
--

COPY dispute.cases (reference, contract_id, contract_reference, organization_id, professional_id, milestone_ids, category, summary, desired_outcome, context, initiated_by, initiator_party, status, currency, disputed_minor, evidence_deadline, evidence_complete, direct_deadline, escalated_at, mediator_identity_id, recommendation, pending_decision, decision, decided_at, closed_at, id, updated_at, created_at, version) FROM stdin;
\.


--
-- Data for Name: evidence_items; Type: TABLE DATA; Schema: dispute; Owner: -
--

COPY dispute.evidence_items (case_id, party, submitted_by, evidence_type, description, items, id, created_at) FROM stdin;
\.


--
-- Data for Name: resolution_proposals; Type: TABLE DATA; Schema: dispute; Owner: -
--

COPY dispute.resolution_proposals (case_id, party, proposed_by, outcome, allocations, note, status, responded_at, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: timeline; Type: TABLE DATA; Schema: dispute; Owner: -
--

COPY dispute.timeline (case_id, kind, actor, text, id, created_at) FROM stdin;
\.


--
-- Data for Name: accounts; Type: TABLE DATA; Schema: escrow; Owner: -
--

COPY escrow.accounts (contract_id, organization_id, professional_id, currency, total_minor, status, funded_minor, held_minor, on_hold_minor, released_minor, refunded_minor, fees_minor, id, updated_at, created_at, version, fee_bps) FROM stdin;
\.


--
-- Data for Name: allocations; Type: TABLE DATA; Schema: escrow; Owner: -
--

COPY escrow.allocations (account_id, milestone_id, sequence, title, amount_minor, state, funding_id, released_minor, fee_minor, refunded_minor, funded_at, released_at, id, updated_at, created_at, version) FROM stdin;
\.


--
-- Data for Name: fundings; Type: TABLE DATA; Schema: escrow; Owner: -
--

COPY escrow.fundings (account_id, organization_id, requested_by, milestone_ids, amount_minor, currency, status, failure_message, captured_at, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: ledger_entries; Type: TABLE DATA; Schema: escrow; Owner: -
--

COPY escrow.ledger_entries (entry_group_id, account_id, entry_type, ledger_account, debit_minor, credit_minor, currency, reference_type, reference_id, milestone_id, memo, id, created_at) FROM stdin;
\.


--
-- Data for Name: releases; Type: TABLE DATA; Schema: escrow; Owner: -
--

COPY escrow.releases (account_id, milestone_id, gross_minor, fee_minor, net_minor, currency, fee_bps, id, created_at) FROM stdin;
\.


--
-- Data for Name: firms; Type: TABLE DATA; Schema: firm; Owner: -
--

COPY firm.firms (legal_name, trading_name, registration_number, hq_country, size_band, primary_category, website, status, created_by, id, updated_at, created_at, version) FROM stdin;
\.


--
-- Data for Name: invitations; Type: TABLE DATA; Schema: firm; Owner: -
--

COPY firm.invitations (firm_id, email, roles, token_hash, status, expires_at, invited_by, responded_at, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: members; Type: TABLE DATA; Schema: firm; Owner: -
--

COPY firm.members (firm_id, identity_id, email, display_name, roles, status, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: consent_records; Type: TABLE DATA; Schema: identity; Owner: -
--

COPY identity.consent_records (identity_id, consent_type, document_version, id, created_at) FROM stdin;
\.


--
-- Data for Name: data_requests; Type: TABLE DATA; Schema: identity; Owner: -
--

COPY identity.data_requests (identity_id, request_type, status, completed_at, id, updated_at, created_at, scheduled_for, expires_at, export_key, detail) FROM stdin;
\.


--
-- Data for Name: duplicate_suspicions; Type: TABLE DATA; Schema: identity; Owner: -
--

COPY identity.duplicate_suspicions (identity_id, other_identity_id, signal, status, user_answer, user_note, resolved_by, resolved_at, resolution_note, kept_identity_id, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: identities; Type: TABLE DATA; Schema: identity; Owner: -
--

COPY identity.identities (email, email_confirmed_at, password_hash, display_name, country, status, platform_roles, personas, primary_persona, signup_organization_name, mfa_secret_enc, mfa_enabled_at, failed_login_count, locked_until, enterprise_federated, id, updated_at, created_at, version, phone_enc, language, time_zone, confirmation_requested_at, mfa_recovery_hashes) FROM stdin;
\.


--
-- Data for Name: identity_links; Type: TABLE DATA; Schema: identity; Owner: -
--

COPY identity.identity_links (identity_id, link_type, target_id, roles, id, updated_at, created_at, target_kind) FROM stdin;
\.


--
-- Data for Name: sessions; Type: TABLE DATA; Schema: identity; Owner: -
--

COPY identity.sessions (identity_id, family_id, refresh_token_hash, auth_strength, auth_time, expires_at, rotated_at, revoked_at, user_agent, id, created_at) FROM stdin;
\.


--
-- Data for Name: collection_items; Type: TABLE DATA; Schema: marketplace; Owner: -
--

COPY marketplace.collection_items (collection_id, professional_id, id, created_at) FROM stdin;
\.


--
-- Data for Name: collections; Type: TABLE DATA; Schema: marketplace; Owner: -
--

COPY marketplace.collections (identity_id, name, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: saved_professionals; Type: TABLE DATA; Schema: marketplace; Owner: -
--

COPY marketplace.saved_professionals (identity_id, professional_id, id, created_at) FROM stdin;
\.


--
-- Data for Name: saved_searches; Type: TABLE DATA; Schema: marketplace; Owner: -
--

COPY marketplace.saved_searches (identity_id, name, params, last_viewed_at, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: specialization_suggestions; Type: TABLE DATA; Schema: marketplace; Owner: -
--

COPY marketplace.specialization_suggestions (identity_id, professional_id, text, name, category_slug, group_slug, description, credential_likely, source, status, resolved_slug, resolved_by, resolved_at, resolution_note, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: taxonomy_nodes; Type: TABLE DATA; Schema: marketplace; Owner: -
--

COPY marketplace.taxonomy_nodes (slug, name, level, parent_id, category_slug, sort_order, requires_credential, regulated, deliverable_templates, credential_hints, status, taxonomy_version, id, updated_at, created_at, requires_insurance) FROM stdin;
finance-and-accounting	Finance & Accounting	CATEGORY	\N	finance-and-accounting	1	f	f	{}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	44e95ddb-ec34-57a1-b1e7-696ac2336767	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
accounting-and-reporting	Accounting & Reporting	GROUP	44e95ddb-ec34-57a1-b1e7-696ac2336767	finance-and-accounting	1	f	f	{"Monthly management accounts","Reconciliations pack","Close checklist and timetable"}	{}	ACTIVE	1	6f2c6789-c2e8-5237-9e16-d4ae28f1490e	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
financial-accounting	Financial Accounting	SPECIALIZATION	6f2c6789-c2e8-5237-9e16-d4ae28f1490e	finance-and-accounting	1	f	f	{"Monthly management accounts","Reconciliations pack","Close checklist and timetable"}	{}	ACTIVE	1	da8d7a0d-7abb-57f8-a6c8-f676393d7c23	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
management-accounting	Management Accounting	SPECIALIZATION	6f2c6789-c2e8-5237-9e16-d4ae28f1490e	finance-and-accounting	2	f	f	{"Monthly management accounts","Reconciliations pack","Close checklist and timetable"}	{}	ACTIVE	1	6ccda730-0d1e-53bd-90e9-d77db35cf240	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
bookkeeping-and-accounting-services	Bookkeeping & Accounting Services	SPECIALIZATION	6f2c6789-c2e8-5237-9e16-d4ae28f1490e	finance-and-accounting	3	f	f	{"Monthly bookkeeping","Bank and card reconciliations","Year-end pack for accountant"}	{}	ACTIVE	1	1a625c1d-de0a-509c-bcd6-47968e5f70a1	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
month-end-quarter-end-close	Month-End / Quarter-End Close	SPECIALIZATION	6f2c6789-c2e8-5237-9e16-d4ae28f1490e	finance-and-accounting	4	f	f	{"Monthly management accounts","Reconciliations pack","Close checklist and timetable"}	{}	ACTIVE	1	4cdc2b25-9a59-5373-90ad-18f03f2b88fe	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
group-consolidation-and-reporting	Group Consolidation & Reporting	SPECIALIZATION	6f2c6789-c2e8-5237-9e16-d4ae28f1490e	finance-and-accounting	5	f	f	{"Monthly management accounts","Reconciliations pack","Close checklist and timetable"}	{}	ACTIVE	1	5249f9b3-d81a-5f20-8437-a7952e44919b	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
technical-accounting-advisory	Technical Accounting Advisory	SPECIALIZATION	6f2c6789-c2e8-5237-9e16-d4ae28f1490e	finance-and-accounting	6	t	f	{"Monthly management accounts","Reconciliations pack","Close checklist and timetable"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	99353595-1044-505d-90a8-417124efa2bd	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
ifrs-reporting	IFRS Reporting	SPECIALIZATION	6f2c6789-c2e8-5237-9e16-d4ae28f1490e	finance-and-accounting	7	t	f	{"Monthly management accounts","Reconciliations pack","Close checklist and timetable"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	d7535b92-43eb-5159-b716-d362693eed76	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
us-gaap-reporting	US GAAP Reporting	SPECIALIZATION	6f2c6789-c2e8-5237-9e16-d4ae28f1490e	finance-and-accounting	8	t	f	{"Monthly management accounts","Reconciliations pack","Close checklist and timetable"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	a6824680-394d-53a0-9f96-fe5db810791b	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
taxation	Taxation	GROUP	44e95ddb-ec34-57a1-b1e7-696ac2336767	finance-and-accounting	2	f	f	{"Tax computation and return","Advisory memo","Filing calendar"}	{}	ACTIVE	1	e2b2b59d-0f03-5d46-90c2-2b55fa579b22	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
corporate-tax-advisory	Corporate Tax Advisory	SPECIALIZATION	e2b2b59d-0f03-5d46-90c2-2b55fa579b22	finance-and-accounting	1	t	f	{"Tax computation and return","Advisory memo","Filing calendar"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	05494f7a-5782-5c74-a0dc-408573688ec2	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
personal-tax-planning	Personal Tax Planning	SPECIALIZATION	e2b2b59d-0f03-5d46-90c2-2b55fa579b22	finance-and-accounting	2	f	f	{"Tax computation and return","Advisory memo","Filing calendar"}	{}	ACTIVE	1	fad83eff-f7d3-525d-af71-d120545031b5	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
international-tax-strategy	International Tax Strategy	SPECIALIZATION	e2b2b59d-0f03-5d46-90c2-2b55fa579b22	finance-and-accounting	3	t	f	{"Tax computation and return","Advisory memo","Filing calendar"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	f4bcc0f2-1b04-5090-b69e-ad6e957be4ce	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
transfer-pricing	Transfer Pricing	SPECIALIZATION	e2b2b59d-0f03-5d46-90c2-2b55fa579b22	finance-and-accounting	4	t	f	{"Tax computation and return","Advisory memo","Filing calendar"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	2f54a9b7-89d8-536a-a318-6f8af58c2f94	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
vat-gst-sales-tax	VAT / GST / Sales Tax	SPECIALIZATION	e2b2b59d-0f03-5d46-90c2-2b55fa579b22	finance-and-accounting	5	f	f	{"Tax computation and return","Advisory memo","Filing calendar"}	{}	ACTIVE	1	15cc8141-0b76-5df9-b12e-732271e5b555	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
tax-compliance-and-filings	Tax Compliance & Filings	SPECIALIZATION	e2b2b59d-0f03-5d46-90c2-2b55fa579b22	finance-and-accounting	6	t	t	{"Tax computation and return","Advisory memo","Filing calendar"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	6e15e4c8-779b-5b23-a8c6-701a03a8dfb0	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	t
r-and-d-credits-and-incentives	R&D Credits & Incentives	SPECIALIZATION	e2b2b59d-0f03-5d46-90c2-2b55fa579b22	finance-and-accounting	7	f	f	{"Tax computation and return","Advisory memo","Filing calendar"}	{}	ACTIVE	1	50a17810-701d-5568-b8f3-ae45de47b732	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
finance-leadership	Finance Leadership	GROUP	44e95ddb-ec34-57a1-b1e7-696ac2336767	finance-and-accounting	3	f	f	{"13-week cash flow forecast","Board reporting pack","Annual budget and KPI dashboard"}	{}	ACTIVE	1	dc50e165-9bf2-5c4f-94e5-f22afd9d7234	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
fractional-cfo	Fractional CFO	SPECIALIZATION	dc50e165-9bf2-5c4f-94e5-f22afd9d7234	finance-and-accounting	1	f	f	{"Financial strategy and operating plan","Investor and board reporting","Fundraising support materials"}	{}	ACTIVE	1	e1cb1dab-07d0-5239-95fd-17f6f1b0e4d8	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
fractional-controller	Fractional Controller	SPECIALIZATION	dc50e165-9bf2-5c4f-94e5-f22afd9d7234	finance-and-accounting	2	f	f	{"13-week cash flow forecast","Board reporting pack","Annual budget and KPI dashboard"}	{}	ACTIVE	1	8c668c85-6628-5d5a-a56b-799bdecba7ad	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
virtual-finance-director	Virtual Finance Director	SPECIALIZATION	dc50e165-9bf2-5c4f-94e5-f22afd9d7234	finance-and-accounting	3	f	f	{"13-week cash flow forecast","Board reporting pack","Annual budget and KPI dashboard"}	{}	ACTIVE	1	8b4b2a05-ea96-5866-b5ff-d1815a4ee882	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
fp-and-a-and-financial-planning	FP&A & Financial Planning	SPECIALIZATION	dc50e165-9bf2-5c4f-94e5-f22afd9d7234	finance-and-accounting	4	f	f	{"13-week cash flow forecast","Board reporting pack","Annual budget and KPI dashboard"}	{}	ACTIVE	1	dd41b6ec-3931-525c-9300-4557635a0034	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
budgeting-and-forecasting	Budgeting & Forecasting	SPECIALIZATION	dc50e165-9bf2-5c4f-94e5-f22afd9d7234	finance-and-accounting	5	f	f	{"13-week cash flow forecast","Board reporting pack","Annual budget and KPI dashboard"}	{}	ACTIVE	1	dc54c690-4261-5197-9bee-d9d684f36e4f	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
treasury-and-cash-management	Treasury & Cash Management	SPECIALIZATION	dc50e165-9bf2-5c4f-94e5-f22afd9d7234	finance-and-accounting	6	f	f	{"13-week cash flow forecast","Board reporting pack","Annual budget and KPI dashboard"}	{}	ACTIVE	1	b5bebd90-1985-5989-a7e6-04fe8fb35109	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
capital-strategy-and-structuring	Capital Strategy & Structuring	SPECIALIZATION	dc50e165-9bf2-5c4f-94e5-f22afd9d7234	finance-and-accounting	7	f	f	{"13-week cash flow forecast","Board reporting pack","Annual budget and KPI dashboard"}	{}	ACTIVE	1	318c2f1e-45ba-5f55-bb02-af7ea651eb82	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
audit-and-assurance	Audit & Assurance	GROUP	44e95ddb-ec34-57a1-b1e7-696ac2336767	finance-and-accounting	4	f	f	{"Audit plan","Controls testing workpapers","Findings report with remediation plan"}	{}	ACTIVE	1	c976a480-afeb-578b-b312-944b96b362ad	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
internal-audit	Internal Audit	SPECIALIZATION	c976a480-afeb-578b-b312-944b96b362ad	finance-and-accounting	1	f	f	{"Audit plan","Controls testing workpapers","Findings report with remediation plan"}	{}	ACTIVE	1	e1d977fa-e3c2-53c3-9bbe-86a2d0925ac8	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
external-audit-support	External Audit Support	SPECIALIZATION	c976a480-afeb-578b-b312-944b96b362ad	finance-and-accounting	2	t	t	{"Audit plan","Controls testing workpapers","Findings report with remediation plan"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	6caf4f94-6b98-5d2d-89a9-868c21475deb	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	t
audit-readiness-and-preparation	Audit Readiness & Preparation	SPECIALIZATION	c976a480-afeb-578b-b312-944b96b362ad	finance-and-accounting	3	f	f	{"Audit plan","Controls testing workpapers","Findings report with remediation plan"}	{}	ACTIVE	1	9d705b4d-5828-5c41-a530-c718ed973343	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
sox-compliance-and-testing	SOX Compliance & Testing	SPECIALIZATION	c976a480-afeb-578b-b312-944b96b362ad	finance-and-accounting	4	t	t	{"Risk and control matrix","Walkthrough documentation","Testing results and deficiency log"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	1ab5f9e2-9d44-5f33-9dd6-5a41f9d50b1e	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	t
internal-controls-design-and-testing	Internal Controls Design & Testing	SPECIALIZATION	c976a480-afeb-578b-b312-944b96b362ad	finance-and-accounting	5	f	f	{"Audit plan","Controls testing workpapers","Findings report with remediation plan"}	{}	ACTIVE	1	fab0de75-c5c9-59b0-9bf1-8bce70f4fbed	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
risk-and-controls-assessment	Risk & Controls Assessment	SPECIALIZATION	c976a480-afeb-578b-b312-944b96b362ad	finance-and-accounting	6	f	f	{"Audit plan","Controls testing workpapers","Findings report with remediation plan"}	{}	ACTIVE	1	eb1565d6-0b96-5eb2-baf4-3d19cbf2d294	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
transaction-and-advisory	Transaction & Advisory	GROUP	44e95ddb-ec34-57a1-b1e7-696ac2336767	finance-and-accounting	5	f	f	{"Due diligence report","Financial model","Valuation summary"}	{}	ACTIVE	1	0ce00274-7a67-5b04-9548-8384f861dc64	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
m-and-a-financial-due-diligence	M&A Financial Due Diligence	SPECIALIZATION	0ce00274-7a67-5b04-9548-8384f861dc64	finance-and-accounting	1	f	f	{"Due diligence report","Financial model","Valuation summary"}	{}	ACTIVE	1	0d08971b-f6be-5df4-9584-5072bae9a9d5	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
valuation-services	Valuation Services	SPECIALIZATION	0ce00274-7a67-5b04-9548-8384f861dc64	finance-and-accounting	2	t	f	{"Due diligence report","Financial model","Valuation summary"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	37139b34-147a-5b42-a2ea-ac0df4b611ec	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
restructuring-and-turnaround	Restructuring & Turnaround	SPECIALIZATION	0ce00274-7a67-5b04-9548-8384f861dc64	finance-and-accounting	3	f	f	{"Due diligence report","Financial model","Valuation summary"}	{}	ACTIVE	1	9736bd51-5cef-5302-8074-7f803b1b320d	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
investment-analysis-and-modeling	Investment Analysis & Modeling	SPECIALIZATION	0ce00274-7a67-5b04-9548-8384f861dc64	finance-and-accounting	4	f	f	{"Due diligence report","Financial model","Valuation summary"}	{}	ACTIVE	1	d8e74fea-b3a7-5719-8c06-cd13b4a0f571	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
carve-out-and-integration-support	Carve-Out & Integration Support	SPECIALIZATION	0ce00274-7a67-5b04-9548-8384f861dc64	finance-and-accounting	5	f	f	{"Due diligence report","Financial model","Valuation summary"}	{}	ACTIVE	1	50a014a5-8706-5778-8f3b-da0ca208805b	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
regulatory-and-compliance-finance	Regulatory & Compliance Finance	GROUP	44e95ddb-ec34-57a1-b1e7-696ac2336767	finance-and-accounting	6	f	f	{"Regulatory return","Compliance testing report","Policy and procedure documentation"}	{}	ACTIVE	1	a2fbef40-ba2e-58f2-9630-fc76a68573dd	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
regulatory-reporting	Regulatory Reporting	SPECIALIZATION	a2fbef40-ba2e-58f2-9630-fc76a68573dd	finance-and-accounting	1	t	t	{"Regulatory return","Compliance testing report","Policy and procedure documentation"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	204c9bcb-bbe7-57e7-a80a-ce7a478ba576	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	t
financial-risk-management	Financial Risk Management	SPECIALIZATION	a2fbef40-ba2e-58f2-9630-fc76a68573dd	finance-and-accounting	2	f	f	{"Regulatory return","Compliance testing report","Policy and procedure documentation"}	{}	ACTIVE	1	a1b84f82-f1a1-523c-a01c-5018245ed152	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
aml-financial-crime-controls	AML / Financial Crime Controls	SPECIALIZATION	a2fbef40-ba2e-58f2-9630-fc76a68573dd	finance-and-accounting	3	t	t	{"Regulatory return","Compliance testing report","Policy and procedure documentation"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	9f927fb3-44a7-530f-a5b2-dcfc8ada18bf	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	t
compliance-documentation-and-testing	Compliance Documentation & Testing	SPECIALIZATION	a2fbef40-ba2e-58f2-9630-fc76a68573dd	finance-and-accounting	4	f	f	{"Regulatory return","Compliance testing report","Policy and procedure documentation"}	{}	ACTIVE	1	83bb6d31-33f4-5ba2-93d1-0f1616e59402	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
ifrs-9-ifrs-17-implementation	IFRS 9 / IFRS 17 Implementation	SPECIALIZATION	a2fbef40-ba2e-58f2-9630-fc76a68573dd	finance-and-accounting	5	t	f	{"Regulatory return","Compliance testing report","Policy and procedure documentation"}	{CPA,CA,ACCA,CMA,CFA,CIA,CGMA,CFE}	ACTIVE	1	8f930b90-0d0d-52a2-94f4-929ca8760455	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
finance-systems-and-technology	Finance Systems & Technology	GROUP	44e95ddb-ec34-57a1-b1e7-696ac2336767	finance-and-accounting	7	f	f	{"Requirements and design document","Configured system with test evidence","User training and handover"}	{}	ACTIVE	1	e751c543-496b-5750-a3ff-88f650449229	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
accounting-systems-implementation	Accounting Systems Implementation	SPECIALIZATION	e751c543-496b-5750-a3ff-88f650449229	finance-and-accounting	1	f	f	{"Requirements and design document","Configured system with test evidence","User training and handover"}	{}	ACTIVE	1	e24ec60d-b02c-54b1-abf6-89cdb1f644be	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
erp-finance-modules	ERP Finance Modules	SPECIALIZATION	e751c543-496b-5750-a3ff-88f650449229	finance-and-accounting	2	f	f	{"Requirements and design document","Configured system with test evidence","User training and handover"}	{}	ACTIVE	1	71cdc05c-7755-5476-98c9-8f359802e74b	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
finance-process-automation	Finance Process Automation	SPECIALIZATION	e751c543-496b-5750-a3ff-88f650449229	finance-and-accounting	3	f	f	{"Requirements and design document","Configured system with test evidence","User training and handover"}	{}	ACTIVE	1	d88c47e6-a521-5563-b05d-4ad7ebb23714	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
financial-reporting-and-bi-tools	Financial Reporting & BI Tools	SPECIALIZATION	e751c543-496b-5750-a3ff-88f650449229	finance-and-accounting	4	f	f	{"Requirements and design document","Configured system with test evidence","User training and handover"}	{}	ACTIVE	1	61ad8cbc-ec9b-5e3d-9909-e01f5a271221	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
finance-data-integration	Finance Data Integration	SPECIALIZATION	e751c543-496b-5750-a3ff-88f650449229	finance-and-accounting	5	f	f	{"Requirements and design document","Configured system with test evidence","User training and handover"}	{}	ACTIVE	1	ae767b3a-1459-56ac-a721-fd014acb54e3	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
technology-and-software-development	Technology & Software Development	CATEGORY	\N	technology-and-software-development	2	f	f	{}	{AWS,Azure,GCP,CISSP,CEH,OSCP,"ISO 27001 LA",PMP}	ACTIVE	1	f164158e-8dbb-535e-a386-66cafa5106ec	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
software-development	Software Development	GROUP	f164158e-8dbb-535e-a386-66cafa5106ec	technology-and-software-development	1	f	f	{"Technical specification","Working software with source code","Deployment and handover notes"}	{}	ACTIVE	1	a5179888-aad9-50c8-80d6-803fac03667d	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
web-development	Web Development	SPECIALIZATION	a5179888-aad9-50c8-80d6-803fac03667d	technology-and-software-development	1	f	f	{"Technical specification","Working software with source code","Deployment and handover notes"}	{}	ACTIVE	1	2e804d72-bf38-5f2d-9356-efdf10fe407e	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
mobile-app-development	Mobile App Development	SPECIALIZATION	a5179888-aad9-50c8-80d6-803fac03667d	technology-and-software-development	2	f	f	{"Technical specification","Working software with source code","Deployment and handover notes"}	{}	ACTIVE	1	29084371-8b5f-5ac2-b31b-bafeb25423a0	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
backend-and-api-development	Backend & API Development	SPECIALIZATION	a5179888-aad9-50c8-80d6-803fac03667d	technology-and-software-development	3	f	f	{"Technical specification","Working software with source code","Deployment and handover notes"}	{}	ACTIVE	1	36a53dc8-5990-58da-b5ee-fa0f14ee7d7d	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
full-stack-development	Full-Stack Development	SPECIALIZATION	a5179888-aad9-50c8-80d6-803fac03667d	technology-and-software-development	4	f	f	{"Technical specification","Working software with source code","Deployment and handover notes"}	{}	ACTIVE	1	2dad45e9-1386-5128-a671-b2b896daac1c	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
software-architecture	Software Architecture	SPECIALIZATION	a5179888-aad9-50c8-80d6-803fac03667d	technology-and-software-development	5	f	f	{"Technical specification","Working software with source code","Deployment and handover notes"}	{}	ACTIVE	1	8001846c-7dac-553f-8350-2207f0265459	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
legacy-system-modernization	Legacy System Modernization	SPECIALIZATION	a5179888-aad9-50c8-80d6-803fac03667d	technology-and-software-development	6	f	f	{"Technical specification","Working software with source code","Deployment and handover notes"}	{}	ACTIVE	1	a8f17db4-9926-555c-a223-15a03ad455b0	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
ai-and-data	AI & Data	GROUP	f164158e-8dbb-535e-a386-66cafa5106ec	technology-and-software-development	2	f	f	{"Data assessment and approach","Model or pipeline with evaluation results","Documentation and handover"}	{}	ACTIVE	1	49f9a083-3b6c-5a85-bb0f-4052418371b2	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
ai-machine-learning-engineering	AI / Machine Learning Engineering	SPECIALIZATION	49f9a083-3b6c-5a85-bb0f-4052418371b2	technology-and-software-development	1	f	f	{"Data assessment and approach","Model or pipeline with evaluation results","Documentation and handover"}	{}	ACTIVE	1	526a2c3f-5f7d-57e8-83f2-d083ef8262a7	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
generative-ai-and-llm-applications	Generative AI & LLM Applications	SPECIALIZATION	49f9a083-3b6c-5a85-bb0f-4052418371b2	technology-and-software-development	2	f	f	{"Data assessment and approach","Model or pipeline with evaluation results","Documentation and handover"}	{}	ACTIVE	1	9d1ffab6-24e4-5f76-9dd6-29cfc2d6b3c2	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
data-engineering	Data Engineering	SPECIALIZATION	49f9a083-3b6c-5a85-bb0f-4052418371b2	technology-and-software-development	3	f	f	{"Data assessment and approach","Model or pipeline with evaluation results","Documentation and handover"}	{}	ACTIVE	1	f02c2601-923b-5e3a-a17f-1ac6e8586a98	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
data-analytics-and-business-intelligence	Data Analytics & Business Intelligence	SPECIALIZATION	49f9a083-3b6c-5a85-bb0f-4052418371b2	technology-and-software-development	4	f	f	{"Data assessment and approach","Model or pipeline with evaluation results","Documentation and handover"}	{}	ACTIVE	1	e61e23c9-78ca-592e-8ec0-cc63eca1e37e	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
data-science-and-statistical-modeling	Data Science & Statistical Modeling	SPECIALIZATION	49f9a083-3b6c-5a85-bb0f-4052418371b2	technology-and-software-development	5	f	f	{"Data assessment and approach","Model or pipeline with evaluation results","Documentation and handover"}	{}	ACTIVE	1	d2af4021-1352-5532-af60-68119d7c5313	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
cloud-and-devops	Cloud & DevOps	GROUP	f164158e-8dbb-535e-a386-66cafa5106ec	technology-and-software-development	3	f	f	{"Architecture design","Infrastructure as code and pipelines","Runbook and handover"}	{}	ACTIVE	1	6bc796a0-1509-55b6-829f-829a19a9213e	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
cloud-architecture	Cloud Architecture	SPECIALIZATION	6bc796a0-1509-55b6-829f-829a19a9213e	technology-and-software-development	1	f	f	{"Architecture design","Infrastructure as code and pipelines","Runbook and handover"}	{}	ACTIVE	1	71f5d2d5-518b-530a-a617-944f4598d85f	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
devops-and-ci-cd	DevOps & CI/CD	SPECIALIZATION	6bc796a0-1509-55b6-829f-829a19a9213e	technology-and-software-development	2	f	f	{"Architecture design","Infrastructure as code and pipelines","Runbook and handover"}	{}	ACTIVE	1	86145d70-6c2a-57ca-89dd-23e91bd4a1d8	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
site-reliability-engineering	Site Reliability Engineering	SPECIALIZATION	6bc796a0-1509-55b6-829f-829a19a9213e	technology-and-software-development	3	f	f	{"Architecture design","Infrastructure as code and pipelines","Runbook and handover"}	{}	ACTIVE	1	dd5693fe-e09d-5bef-b387-21ce9e2ff2cf	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
cloud-migration	Cloud Migration	SPECIALIZATION	6bc796a0-1509-55b6-829f-829a19a9213e	technology-and-software-development	4	f	f	{"Architecture design","Infrastructure as code and pipelines","Runbook and handover"}	{}	ACTIVE	1	521be22a-c0a0-5450-ac33-a3cb91551dd4	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
cybersecurity	Cybersecurity	GROUP	f164158e-8dbb-535e-a386-66cafa5106ec	technology-and-software-development	4	f	f	{"Assessment scope and plan","Findings report with risk ratings","Remediation plan"}	{}	ACTIVE	1	e93e39b1-fff0-500b-9158-eb4a9e021ed7	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
application-security	Application Security	SPECIALIZATION	e93e39b1-fff0-500b-9158-eb4a9e021ed7	technology-and-software-development	1	f	f	{"Assessment scope and plan","Findings report with risk ratings","Remediation plan"}	{}	ACTIVE	1	f64e37dc-06b4-54ef-b8a6-d20d8e4fecc7	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
penetration-testing	Penetration Testing	SPECIALIZATION	e93e39b1-fff0-500b-9158-eb4a9e021ed7	technology-and-software-development	2	t	f	{"Assessment scope and plan","Findings report with risk ratings","Remediation plan"}	{AWS,Azure,GCP,CISSP,CEH,OSCP,"ISO 27001 LA",PMP}	ACTIVE	1	e0fce7e0-72b8-5a4e-bf70-c6fcdbeec60a	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
security-compliance-iso-27001-soc-2	Security Compliance (ISO 27001 / SOC 2)	SPECIALIZATION	e93e39b1-fff0-500b-9158-eb4a9e021ed7	technology-and-software-development	3	t	f	{"Assessment scope and plan","Findings report with risk ratings","Remediation plan"}	{AWS,Azure,GCP,CISSP,CEH,OSCP,"ISO 27001 LA",PMP}	ACTIVE	1	66868d43-78b1-5b8d-971b-509517527364	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
identity-and-access-management	Identity & Access Management	SPECIALIZATION	e93e39b1-fff0-500b-9158-eb4a9e021ed7	technology-and-software-development	4	f	f	{"Assessment scope and plan","Findings report with risk ratings","Remediation plan"}	{}	ACTIVE	1	10e8b54d-86c6-5bde-9e06-cdbb1616c17a	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
product-design-and-quality	Product, Design & Quality	GROUP	f164158e-8dbb-535e-a386-66cafa5106ec	technology-and-software-development	5	f	f	{"Discovery findings","Designs or test suite","Handover and recommendations"}	{}	ACTIVE	1	7251d738-fc78-5469-b087-809957f5726f	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
ux-ui-design	UX / UI Design	SPECIALIZATION	7251d738-fc78-5469-b087-809957f5726f	technology-and-software-development	1	f	f	{"Discovery findings","Designs or test suite","Handover and recommendations"}	{}	ACTIVE	1	e9323f01-6fda-56d9-9f38-c1ec16ce9cfc	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
product-management	Product Management	SPECIALIZATION	7251d738-fc78-5469-b087-809957f5726f	technology-and-software-development	2	f	f	{"Discovery findings","Designs or test suite","Handover and recommendations"}	{}	ACTIVE	1	c7f36323-1b4c-516c-9869-e24982e779a3	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
qa-and-test-automation	QA & Test Automation	SPECIALIZATION	7251d738-fc78-5469-b087-809957f5726f	technology-and-software-development	3	f	f	{"Discovery findings","Designs or test suite","Handover and recommendations"}	{}	ACTIVE	1	5ff31033-7354-59e2-9008-f6f684d5487e	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
technical-project-management	Technical Project Management	SPECIALIZATION	7251d738-fc78-5469-b087-809957f5726f	technology-and-software-development	4	f	f	{"Discovery findings","Designs or test suite","Handover and recommendations"}	{}	ACTIVE	1	4a5d1e25-f81b-5dcb-90e8-ce78108ceb98	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
legal-services	Legal Services	CATEGORY	\N	legal-services	3	f	f	{}	{"Bar admission",Solicitor,Attorney,Advocate}	ACTIVE	1	81cc1079-1f58-5cb6-b991-ee7ef9269c9c	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
corporate-and-commercial-law	Corporate & Commercial Law	GROUP	81cc1079-1f58-5cb6-b991-ee7ef9269c9c	legal-services	1	f	f	{"Legal advice memo","Drafted or reviewed agreement","Negotiation support notes"}	{}	ACTIVE	1	ff4a2593-d043-549f-9bbc-c01b4914e057	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
commercial-contracts	Commercial Contracts	SPECIALIZATION	ff4a2593-d043-549f-9bbc-c01b4914e057	legal-services	1	t	t	{"Legal advice memo","Drafted or reviewed agreement","Negotiation support notes"}	{"Bar admission",Solicitor,Attorney,Advocate}	ACTIVE	1	bbf7544d-3e50-5181-b158-f3557991edf2	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	t
corporate-governance-and-company-secretarial	Corporate Governance & Company Secretarial	SPECIALIZATION	ff4a2593-d043-549f-9bbc-c01b4914e057	legal-services	2	t	t	{"Legal advice memo","Drafted or reviewed agreement","Negotiation support notes"}	{"Bar admission",Solicitor,Attorney,Advocate}	ACTIVE	1	bcecba2c-6531-5103-92c4-89aff720cd4a	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	t
m-and-a-legal-advisory	M&A Legal Advisory	SPECIALIZATION	ff4a2593-d043-549f-9bbc-c01b4914e057	legal-services	3	t	t	{"Legal advice memo","Drafted or reviewed agreement","Negotiation support notes"}	{"Bar admission",Solicitor,Attorney,Advocate}	ACTIVE	1	a11af046-62c3-539c-b298-62fc006c90c5	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	t
employment-and-immigration-law	Employment & Immigration Law	GROUP	81cc1079-1f58-5cb6-b991-ee7ef9269c9c	legal-services	2	f	f	{"Legal advice memo","Drafted policies or contracts","Filing or application pack"}	{}	ACTIVE	1	cac6e07b-319f-5eb3-af3f-13fcb5a414cc	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
employment-law	Employment Law	SPECIALIZATION	cac6e07b-319f-5eb3-af3f-13fcb5a414cc	legal-services	1	t	t	{"Legal advice memo","Drafted policies or contracts","Filing or application pack"}	{"Bar admission",Solicitor,Attorney,Advocate}	ACTIVE	1	7f3df228-920f-5170-9423-02db30a99df1	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	t
immigration-law	Immigration Law	SPECIALIZATION	cac6e07b-319f-5eb3-af3f-13fcb5a414cc	legal-services	2	t	t	{"Legal advice memo","Drafted policies or contracts","Filing or application pack"}	{"Bar admission",Solicitor,Attorney,Advocate}	ACTIVE	1	830c52a7-1a9e-5313-9411-e0b633f026f6	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	t
intellectual-property	Intellectual Property	GROUP	81cc1079-1f58-5cb6-b991-ee7ef9269c9c	legal-services	3	f	f	{"Clearance or search report","Filing documents","Licence agreement"}	{}	ACTIVE	1	0d40eac5-f146-51eb-be98-5c43c789bd67	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
trademarks-and-patents	Trademarks & Patents	SPECIALIZATION	0d40eac5-f146-51eb-be98-5c43c789bd67	legal-services	1	t	t	{"Clearance or search report","Filing documents","Licence agreement"}	{"Bar admission",Solicitor,Attorney,Advocate}	ACTIVE	1	86a7f336-cdfa-58ac-9ecc-29f7daccbd0b	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	t
technology-licensing-agreements	Technology Licensing Agreements	SPECIALIZATION	0d40eac5-f146-51eb-be98-5c43c789bd67	legal-services	2	t	t	{"Clearance or search report","Filing documents","Licence agreement"}	{"Bar admission",Solicitor,Attorney,Advocate}	ACTIVE	1	85111db9-da3a-5c96-ace6-bc2f08bf82a8	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	t
privacy-and-regulatory-law	Privacy & Regulatory Law	GROUP	81cc1079-1f58-5cb6-b991-ee7ef9269c9c	legal-services	4	f	f	{"Gap assessment","Policies and notices","Compliance roadmap"}	{}	ACTIVE	1	b1de7dae-4efa-5090-b3b4-373b80df9de0	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
data-privacy-and-gdpr	Data Privacy & GDPR	SPECIALIZATION	b1de7dae-4efa-5090-b3b4-373b80df9de0	legal-services	1	t	f	{"Gap assessment","Policies and notices","Compliance roadmap"}	{"Bar admission",Solicitor,Attorney,Advocate}	ACTIVE	1	40ae9be6-e1f2-55be-9491-34f803151716	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
regulatory-compliance-advisory	Regulatory Compliance Advisory	SPECIALIZATION	b1de7dae-4efa-5090-b3b4-373b80df9de0	legal-services	2	t	f	{"Gap assessment","Policies and notices","Compliance roadmap"}	{"Bar admission",Solicitor,Attorney,Advocate}	ACTIVE	1	9756a0f8-2df6-51e8-b7b0-5d3cecf0dbb0	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
hr-and-people	HR & People	CATEGORY	\N	hr-and-people	4	f	f	{}	{CIPD,SHRM-CP,SHRM-SCP}	ACTIVE	1	afbc2141-8840-513d-8fb9-57830d9bbe36	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
talent-acquisition	Talent Acquisition	GROUP	afbc2141-8840-513d-8fb9-57830d9bbe36	hr-and-people	1	f	f	{"Role profile and search plan","Shortlist with assessments","Offer and onboarding support"}	{}	ACTIVE	1	5062ed1f-a37d-54bc-bab9-716b11ce0c9f	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
recruitment-and-talent-acquisition	Recruitment & Talent Acquisition	SPECIALIZATION	5062ed1f-a37d-54bc-bab9-716b11ce0c9f	hr-and-people	1	f	f	{"Role profile and search plan","Shortlist with assessments","Offer and onboarding support"}	{}	ACTIVE	1	f1526727-2d04-5b03-9070-d0d5571a248f	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
executive-search	Executive Search	SPECIALIZATION	5062ed1f-a37d-54bc-bab9-716b11ce0c9f	hr-and-people	2	f	f	{"Role profile and search plan","Shortlist with assessments","Offer and onboarding support"}	{}	ACTIVE	1	2c16ee99-6961-5596-b371-0f3c6b1ba4f3	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
people-operations	People Operations	GROUP	afbc2141-8840-513d-8fb9-57830d9bbe36	hr-and-people	2	f	f	{"Policy pack","Process documentation","Compliance checklist"}	{}	ACTIVE	1	39f6cd9f-bbd9-5bbe-81ac-9f20a10d76d9	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
hr-policy-and-compliance	HR Policy & Compliance	SPECIALIZATION	39f6cd9f-bbd9-5bbe-81ac-9f20a10d76d9	hr-and-people	1	f	f	{"Policy pack","Process documentation","Compliance checklist"}	{}	ACTIVE	1	92998e66-4143-5d34-b60b-ce263163443f	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
payroll-administration	Payroll Administration	SPECIALIZATION	39f6cd9f-bbd9-5bbe-81ac-9f20a10d76d9	hr-and-people	2	f	f	{"Policy pack","Process documentation","Compliance checklist"}	{}	ACTIVE	1	86f40a56-214b-5b5c-8b39-1a33e88111ca	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
compensation-and-benefits	Compensation & Benefits	SPECIALIZATION	39f6cd9f-bbd9-5bbe-81ac-9f20a10d76d9	hr-and-people	3	f	f	{"Policy pack","Process documentation","Compliance checklist"}	{}	ACTIVE	1	6bdbefbf-1ab7-5328-8d05-5de43e4de690	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
organisation-development	Organisation Development	GROUP	afbc2141-8840-513d-8fb9-57830d9bbe36	hr-and-people	3	f	f	{"Assessment findings","Programme or structure design","Implementation plan"}	{}	ACTIVE	1	0d6d6e53-e7c5-5e0e-b50b-347e0103cd4b	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
learning-and-development	Learning & Development	SPECIALIZATION	0d6d6e53-e7c5-5e0e-b50b-347e0103cd4b	hr-and-people	1	f	f	{"Assessment findings","Programme or structure design","Implementation plan"}	{}	ACTIVE	1	d606e033-f909-5640-840d-de5c2b92264a	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
organisational-design	Organisational Design	SPECIALIZATION	0d6d6e53-e7c5-5e0e-b50b-347e0103cd4b	hr-and-people	2	f	f	{"Assessment findings","Programme or structure design","Implementation plan"}	{}	ACTIVE	1	3d21695b-4931-561d-81cf-ad7d49bce15f	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
fractional-hr-leadership	Fractional HR Leadership	SPECIALIZATION	0d6d6e53-e7c5-5e0e-b50b-347e0103cd4b	hr-and-people	3	f	f	{"Assessment findings","Programme or structure design","Implementation plan"}	{}	ACTIVE	1	1de44aa8-1436-5b9e-85cf-41ea56cb22d9	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
marketing-and-growth	Marketing & Growth	CATEGORY	\N	marketing-and-growth	5	f	f	{}	{}	ACTIVE	1	99523256-ac1a-5210-81cb-0b3e940eda43	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
digital-marketing	Digital Marketing	GROUP	99523256-ac1a-5210-81cb-0b3e940eda43	marketing-and-growth	1	f	f	{"Channel audit","Campaign plan and setup","Performance report"}	{}	ACTIVE	1	64c860c4-ea85-53a0-912d-e8ab262bfc0c	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
search-engine-optimization-seo	Search Engine Optimization (SEO)	SPECIALIZATION	64c860c4-ea85-53a0-912d-e8ab262bfc0c	marketing-and-growth	1	f	f	{"Channel audit","Campaign plan and setup","Performance report"}	{}	ACTIVE	1	2192c315-c070-5e4d-a4d0-013cc3fa99e9	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
paid-media-and-performance-marketing	Paid Media & Performance Marketing	SPECIALIZATION	64c860c4-ea85-53a0-912d-e8ab262bfc0c	marketing-and-growth	2	f	f	{"Channel audit","Campaign plan and setup","Performance report"}	{}	ACTIVE	1	808ac3dc-3cca-56b0-be9c-74a90c0319e1	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
social-media-marketing	Social Media Marketing	SPECIALIZATION	64c860c4-ea85-53a0-912d-e8ab262bfc0c	marketing-and-growth	3	f	f	{"Channel audit","Campaign plan and setup","Performance report"}	{}	ACTIVE	1	7870c1c7-4e26-5c13-88d9-fafca1e0e611	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
email-and-lifecycle-marketing	Email & Lifecycle Marketing	SPECIALIZATION	64c860c4-ea85-53a0-912d-e8ab262bfc0c	marketing-and-growth	4	f	f	{"Channel audit","Campaign plan and setup","Performance report"}	{}	ACTIVE	1	8b24c03b-266b-558e-93db-8899056d5109	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
brand-and-content	Brand & Content	GROUP	99523256-ac1a-5210-81cb-0b3e940eda43	marketing-and-growth	2	f	f	{"Brand or content strategy","Content assets",Guidelines}	{}	ACTIVE	1	9f17e580-1502-58fa-b287-cd1552fe7f6d	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
brand-strategy	Brand Strategy	SPECIALIZATION	9f17e580-1502-58fa-b287-cd1552fe7f6d	marketing-and-growth	1	f	f	{"Brand or content strategy","Content assets",Guidelines}	{}	ACTIVE	1	a3a7a66a-12ec-530d-8bee-0ee9b21e9d0b	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
content-strategy-and-copywriting	Content Strategy & Copywriting	SPECIALIZATION	9f17e580-1502-58fa-b287-cd1552fe7f6d	marketing-and-growth	2	f	f	{"Brand or content strategy","Content assets",Guidelines}	{}	ACTIVE	1	c377bde0-cd8a-55ec-82bc-f82082cfb668	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
pr-and-communications	PR & Communications	SPECIALIZATION	9f17e580-1502-58fa-b287-cd1552fe7f6d	marketing-and-growth	3	f	f	{"Brand or content strategy","Content assets",Guidelines}	{}	ACTIVE	1	bba0743d-a7c3-5166-8184-27c0f2714e55	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
growth-and-analytics	Growth & Analytics	GROUP	99523256-ac1a-5210-81cb-0b3e940eda43	marketing-and-growth	3	f	f	{"Growth plan","Measurement framework and dashboards","Experiment results"}	{}	ACTIVE	1	624ea078-104a-5350-a747-6b7895658ed3	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
growth-strategy	Growth Strategy	SPECIALIZATION	624ea078-104a-5350-a747-6b7895658ed3	marketing-and-growth	1	f	f	{"Growth plan","Measurement framework and dashboards","Experiment results"}	{}	ACTIVE	1	fa715e35-0224-5c74-aadf-8d608f8e552c	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
marketing-analytics	Marketing Analytics	SPECIALIZATION	624ea078-104a-5350-a747-6b7895658ed3	marketing-and-growth	2	f	f	{"Growth plan","Measurement framework and dashboards","Experiment results"}	{}	ACTIVE	1	a213d1a9-42e6-52c2-86ce-e94e2858c5f0	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
fractional-cmo	Fractional CMO	SPECIALIZATION	624ea078-104a-5350-a747-6b7895658ed3	marketing-and-growth	3	f	f	{"Growth plan","Measurement framework and dashboards","Experiment results"}	{}	ACTIVE	1	04bc9b49-95e6-56cd-8fe3-651521369cbe	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
management-consulting	Management Consulting	CATEGORY	\N	management-consulting	6	f	f	{}	{PMP,"Lean Six Sigma",PRINCE2}	ACTIVE	1	3fd78747-8949-52fc-a01e-2e46adfc9e86	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
strategy	Strategy	GROUP	3fd78747-8949-52fc-a01e-2e46adfc9e86	management-consulting	1	f	f	{"Situation analysis","Strategy options and recommendation",Roadmap}	{}	ACTIVE	1	8dccb06a-1b7d-5d84-9145-f180fcac19da	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
business-strategy	Business Strategy	SPECIALIZATION	8dccb06a-1b7d-5d84-9145-f180fcac19da	management-consulting	1	f	f	{"Situation analysis","Strategy options and recommendation",Roadmap}	{}	ACTIVE	1	ad05482d-01e7-50ef-8b6d-0e794dbe54f6	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
market-entry-strategy	Market Entry Strategy	SPECIALIZATION	8dccb06a-1b7d-5d84-9145-f180fcac19da	management-consulting	2	f	f	{"Situation analysis","Strategy options and recommendation",Roadmap}	{}	ACTIVE	1	af8a3eaf-eaa3-52df-9dfe-9b2d7871d684	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
commercial-due-diligence	Commercial Due Diligence	SPECIALIZATION	8dccb06a-1b7d-5d84-9145-f180fcac19da	management-consulting	3	f	f	{"Situation analysis","Strategy options and recommendation",Roadmap}	{}	ACTIVE	1	7edf4a3c-d77a-566b-b002-cde852cc80e6	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
operations	Operations	GROUP	3fd78747-8949-52fc-a01e-2e46adfc9e86	management-consulting	2	f	f	{"Current-state assessment","Improvement plan","Implementation support report"}	{}	ACTIVE	1	d96d3b6b-0a2a-52c3-9a30-71f35ca1c952	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
operations-improvement	Operations Improvement	SPECIALIZATION	d96d3b6b-0a2a-52c3-9a30-71f35ca1c952	management-consulting	1	f	f	{"Current-state assessment","Improvement plan","Implementation support report"}	{}	ACTIVE	1	a811ccfe-3ac4-591d-a8aa-6902a0cdff22	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
supply-chain-consulting	Supply Chain Consulting	SPECIALIZATION	d96d3b6b-0a2a-52c3-9a30-71f35ca1c952	management-consulting	2	f	f	{"Current-state assessment","Improvement plan","Implementation support report"}	{}	ACTIVE	1	1034904b-dc5b-5aff-84a6-dc74598d1ee8	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
lean-six-sigma-process-excellence	Lean / Six Sigma Process Excellence	SPECIALIZATION	d96d3b6b-0a2a-52c3-9a30-71f35ca1c952	management-consulting	3	f	f	{"Current-state assessment","Improvement plan","Implementation support report"}	{}	ACTIVE	1	bca9a59c-478e-5ea6-b62e-f29e6e67174f	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
transformation	Transformation	GROUP	3fd78747-8949-52fc-a01e-2e46adfc9e86	management-consulting	3	f	f	{"Transformation roadmap","Governance and change plan","Progress reporting"}	{}	ACTIVE	1	6e18fbd8-29b7-5ea6-bdb1-98c6c456a3c7	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
digital-transformation	Digital Transformation	SPECIALIZATION	6e18fbd8-29b7-5ea6-bdb1-98c6c456a3c7	management-consulting	1	f	f	{"Transformation roadmap","Governance and change plan","Progress reporting"}	{}	ACTIVE	1	1a9d8c36-d708-5e9d-b79f-e4762e7e8305	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
change-management	Change Management	SPECIALIZATION	6e18fbd8-29b7-5ea6-bdb1-98c6c456a3c7	management-consulting	2	f	f	{"Transformation roadmap","Governance and change plan","Progress reporting"}	{}	ACTIVE	1	a47ac0f9-aec4-50c7-a8e4-2158b3872cf1	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
programme-management-pmo	Programme Management (PMO)	SPECIALIZATION	6e18fbd8-29b7-5ea6-bdb1-98c6c456a3c7	management-consulting	3	f	f	{"Transformation roadmap","Governance and change plan","Progress reporting"}	{}	ACTIVE	1	bcbc41d7-08a5-5be4-b062-656de022a130	2026-10-09 06:57:02.577414+00	2026-10-09 06:57:02.577414+00	f
\.


--
-- Data for Name: attachments; Type: TABLE DATA; Schema: messaging; Owner: -
--

COPY messaging.attachments (thread_id, uploaded_by, name, content_type, size_bytes, sha256, storage_key, file_version, id, created_at) FROM stdin;
\.


--
-- Data for Name: dispute_contexts; Type: TABLE DATA; Schema: messaging; Owner: -
--

COPY messaging.dispute_contexts (dispute_id, contract_id, category, initiated_by_identity_id, is_open, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: messages; Type: TABLE DATA; Schema: messaging; Owner: -
--

COPY messaging.messages (thread_id, sequence, sender_identity_id, sender_name, body, attachment_ids, content_hash, source_event_id, flags, id, created_at) FROM stdin;
\.


--
-- Data for Name: read_positions; Type: TABLE DATA; Schema: messaging; Owner: -
--

COPY messaging.read_positions (thread_id, identity_id, sequence, updated_at, id, created_at) FROM stdin;
\.


--
-- Data for Name: threads; Type: TABLE DATA; Schema: messaging; Owner: -
--

COPY messaging.threads (context_type, context_id, organization_id, professional_id, title, sequence, locked, lock_reason, updated_at, id, created_at) FROM stdin;
\.


--
-- Data for Name: delivery_attempts; Type: TABLE DATA; Schema: notification; Owner: -
--

COPY notification.delivery_attempts (delivery_id, response_status, error, attempt, id, created_at) FROM stdin;
\.


--
-- Data for Name: notifications; Type: TABLE DATA; Schema: notification; Owner: -
--

COPY notification.notifications (source_event_id, identity_id, event_type, title, body, url, notice, in_app, mandatory, read_at, email_status, email_attempts, delivered_at, last_error, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: preferences; Type: TABLE DATA; Schema: notification; Owner: -
--

COPY notification.preferences (identity_id, email, in_app, sms, marketing, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: webhook_deliveries; Type: TABLE DATA; Schema: notification; Owner: -
--

COPY notification.webhook_deliveries (endpoint_id, source_event_id, body, status, attempts, retry_until, delivered_at, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: webhook_endpoints; Type: TABLE DATA; Schema: notification; Owner: -
--

COPY notification.webhook_endpoints (organization_id, url, secret_encrypted, event_types, enabled, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: invoices; Type: TABLE DATA; Schema: payments; Owner: -
--

COPY payments.invoices (number, release_id, organization_id, contract_id, milestone_id, lines, tax_minor, total_minor, currency, issued_at, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: payment_intents; Type: TABLE DATA; Schema: payments; Owner: -
--

COPY payments.payment_intents (funding_id, escrow_account_id, contract_id, organization_id, amount_minor, currency, status, provider, provider_ref, method_label, failure_code, failure_message, captured_at, id, updated_at, created_at, charged_back_at, chargeback_minor, chargeback_reason) FROM stdin;
\.


--
-- Data for Name: payout_accounts; Type: TABLE DATA; Schema: payments; Owner: -
--

COPY payments.payout_accounts (professional_id, holder_name, country, currency, last4, provider, provider_account_ref, status, created_by, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: payouts; Type: TABLE DATA; Schema: payments; Owner: -
--

COPY payments.payouts (release_id, professional_id, contract_id, milestone_id, gross_minor, fee_minor, amount_minor, currency, status, provider_ref, failure_message, settled_at, id, updated_at, created_at, expected_at, transfer_ref, provider_attempt) FROM stdin;
\.


--
-- Data for Name: reconciliation_batches; Type: TABLE DATA; Schema: payments; Owner: -
--

COPY payments.reconciliation_batches (day, status, checks, mismatches, run_by, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: refunds; Type: TABLE DATA; Schema: payments; Owner: -
--

COPY payments.refunds (escrow_refund_id, payment_intent_id, organization_id, contract_id, milestone_id, dispute_id, amount_minor, currency, status, provider_ref, settled_at, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: webhook_events; Type: TABLE DATA; Schema: payments; Owner: -
--

COPY payments.webhook_events (provider, event_id, event_type, payload, outcome, id, created_at) FROM stdin;
\.


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: platform; Owner: -
--

COPY platform.alembic_version (version_num) FROM stdin;
632f70603204
\.


--
-- Data for Name: consumer_failures; Type: TABLE DATA; Schema: platform; Owner: -
--

COPY platform.consumer_failures (consumer, event_id, event_type, envelope, attempts, last_error, status, financial, next_attempt_at, id, created_at) FROM stdin;
\.


--
-- Data for Name: idempotency_keys; Type: TABLE DATA; Schema: platform; Owner: -
--

COPY platform.idempotency_keys (scope, request_hash, response_status, response_body, created_at) FROM stdin;
\.


--
-- Data for Name: inbox; Type: TABLE DATA; Schema: platform; Owner: -
--

COPY platform.inbox (id, consumer, event_id, created_at) FROM stdin;
\.


--
-- Data for Name: outbox; Type: TABLE DATA; Schema: platform; Owner: -
--

COPY platform.outbox (seq, event_id, event_type, aggregate_type, aggregate_id, tenant_id, envelope, published_at, created_at) FROM stdin;
\.


--
-- Data for Name: approval_requests; Type: TABLE DATA; Schema: policy; Owner: -
--

COPY policy.approval_requests (organization_id, policy_version_id, subject_type, subject_id, action, requester_identity_id, context_hash, request_key, attributes, workflows, reasons, status, deadline, escalation_role, escalation_count, step_up_required, id, updated_at, created_at, version) FROM stdin;
\.


--
-- Data for Name: approval_votes; Type: TABLE DATA; Schema: policy; Owner: -
--

COPY policy.approval_votes (request_id, step_id, identity_id, authority_role, decision, reason, id, created_at) FROM stdin;
\.


--
-- Data for Name: exception_requests; Type: TABLE DATA; Schema: policy; Owner: -
--

COPY policy.exception_requests (organization_id, policy_version_id, subject_type, subject_id, action, context_hash, requester_identity_id, justification, documents, status, expires_at, decided_by, decision_reason, decided_at, id, updated_at, created_at, version) FROM stdin;
\.


--
-- Data for Name: policy_evaluations; Type: TABLE DATA; Schema: policy; Owner: -
--

COPY policy.policy_evaluations (organization_id, policy_version_id, policy_profile_id, policy_version_label, subject_type, subject_id, action, actor_identity_id, attributes, context_hash, decision, reasons, dry_run, id, created_at) FROM stdin;
\.


--
-- Data for Name: profiles; Type: TABLE DATA; Schema: policy; Owner: -
--

COPY policy.profiles (organization_id, name, description, risk_level, business_unit_ids, active_version_id, draft_version_id, id, updated_at, created_at, version) FROM stdin;
\.


--
-- Data for Name: versions; Type: TABLE DATA; Schema: policy; Owner: -
--

COPY policy.versions (profile_id, number, status, settings, rules, created_by, activated_by, activated_at, id, created_at) FROM stdin;
\.


--
-- Data for Name: credential_claims; Type: TABLE DATA; Schema: professional; Owner: -
--

COPY professional.credential_claims (professional_id, credential_type, name, issuing_body, registration_number, jurisdiction, issued_on, expires_on, specialization, status, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: offerings; Type: TABLE DATA; Schema: professional; Owner: -
--

COPY professional.offerings (professional_id, title, specialization, summary, deliverables, engagement_types, pricing_model, starting_price_minor, currency, typical_duration, status, id, updated_at, created_at, version) FROM stdin;
\.


--
-- Data for Name: professionals; Type: TABLE DATA; Schema: professional; Owner: -
--

COPY professional.professionals (identity_id, firm_id, status, display_name, legal_name, headline, years_experience_band, bio, languages, country, city, website, primary_category, primary_specialization, secondary_specializations, engagement_types, delivery_modes, pricing_models, rate_minor, rate_currency, rate_unit, availability, max_concurrent_engagements, temporarily_unavailable, active_engagements, served_jurisdictions, licensed_jurisdictions, cross_border_acknowledged_at, accuracy_attested_at, published_at, visibility_reduced, id, updated_at, created_at, version, photo_key, photo_content_type, photo_sha256, weekly_hours) FROM stdin;
\.


--
-- Data for Name: saved_buyers; Type: TABLE DATA; Schema: professional; Owner: -
--

COPY professional.saved_buyers (professional_id, organization_id, note, alerts, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: proposals; Type: TABLE DATA; Schema: proposal; Owner: -
--

COPY proposal.proposals (request_id, organization_id, buyer_identity_id, professional_id, status, summary, scope_alignment, scope_notes, deliverables, milestones, pricing_model, total_minor, currency, start_date, end_date, assumptions, exclusions, valid_until, revision_requests, revision_count, submitted_at, decided_at, decided_by, reason_code, reason_note, terms_hash, id, updated_at, created_at, version, attachments, policy_version_id) FROM stdin;
\.


--
-- Data for Name: requests; Type: TABLE DATA; Schema: proposal; Owner: -
--

COPY proposal.requests (organization_id, buyer_identity_id, professional_id, offering_id, group_id, service, specialization, engagement_type, business_context, objective, details, desired_start_date, estimated_duration, budget_min_minor, budget_max_minor, budget_currency, delivery_mode, location, nda_required, nda_accepted_at, attachments, status, sent_at, closed_at, reason_code, reason_note, id, updated_at, created_at, version, deliverables, dependencies, pricing_preferences, payment_cadence, cost_center_id) FROM stdin;
\.


--
-- Data for Name: reviews; Type: TABLE DATA; Schema: review; Owner: -
--

COPY review.reviews (contract_id, organization_id, professional_id, reviewer_identity_id, reviewer_name, organization_name, rating, comment, engagement_reference, id, created_at) FROM stdin;
\.


--
-- Data for Name: professional_documents; Type: TABLE DATA; Schema: search; Owner: -
--

COPY search.professional_documents (professional_id, visible, visibility_reduced, display_name, headline, country, city, years_experience_band, languages, categories, primary_specialization, specializations, specialization_names, engagement_types, delivery_modes, pricing_models, availability, served_jurisdictions, licensed_jurisdictions, tier, trust_score, dimensions, verified_credentials, offering_titles, starting_price_minor, price_currency, bio_excerpt, published_at, last_event_at, document, id, updated_at, created_at, verified_jurisdictions, photo_url, completed_engagements, milestones_due, milestones_on_time, review_count, review_average, response_median_hours) FROM stdin;
\.


--
-- Data for Name: profiles; Type: TABLE DATA; Schema: trust; Owner: -
--

COPY trust.profiles (professional_id, tier, score, dimensions, explanation, flags, engagement_suspended, recomputed_at, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: signals; Type: TABLE DATA; Schema: trust; Owner: -
--

COPY trust.signals (professional_id, source_event_id, source_event_type, signal_type, adverse, summary, id, created_at) FROM stdin;
\.


--
-- Data for Name: tier_history; Type: TABLE DATA; Schema: trust; Owner: -
--

COPY trust.tier_history (professional_id, from_tier, to_tier, reasons, source_event_type, id, created_at) FROM stdin;
\.


--
-- Data for Name: appeals; Type: TABLE DATA; Schema: verification; Owner: -
--

COPY verification.appeals (case_id, filed_by, statement, case_status_at_filing, original_reviewer_id, status, decided_by, decided_at, decision_note, id, updated_at, created_at) FROM stdin;
\.


--
-- Data for Name: cases; Type: TABLE DATA; Schema: verification; Owner: -
--

COPY verification.cases (subject_type, subject_id, owner_identity_id, verification_type, status, label, jurisdiction, credential_claim_id, specialization, details, provider_result, estimated_completion, reviewer_id, decided_at, verified_at, expires_at, reason_code, public_reason, id, updated_at, created_at, version) FROM stdin;
\.


--
-- Data for Name: evidence_checks; Type: TABLE DATA; Schema: verification; Owner: -
--

COPY verification.evidence_checks (evidence_id, case_id, verdict, seen, note, source, id, created_at) FROM stdin;
\.


--
-- Data for Name: evidence_items; Type: TABLE DATA; Schema: verification; Owner: -
--

COPY verification.evidence_items (case_id, evidence_type, file_name, sha256, size_bytes, storage_key, uploaded_by, id, created_at, content_type, storage_version) FROM stdin;
\.


--
-- Data for Name: provider_events; Type: TABLE DATA; Schema: verification; Owner: -
--

COPY verification.provider_events (id, created_at, event_id, event_type, payload_sha256) FROM stdin;
\.


--
-- Data for Name: provider_sessions; Type: TABLE DATA; Schema: verification; Owner: -
--

COPY verification.provider_sessions (id, created_at, updated_at, case_id, provider_ref, status, provider, hosted_url, reason) FROM stdin;
\.


--
-- Name: event_facts_seq_seq; Type: SEQUENCE SET; Schema: analytics; Owner: -
--

SELECT pg_catalog.setval('analytics.event_facts_seq_seq', 1, false);


--
-- Name: audit_records_seq_seq; Type: SEQUENCE SET; Schema: audit; Owner: -
--

SELECT pg_catalog.setval('audit.audit_records_seq_seq', 1, false);


--
-- Name: invoice_number_seq; Type: SEQUENCE SET; Schema: payments; Owner: -
--

SELECT pg_catalog.setval('payments.invoice_number_seq', 1, false);


--
-- Name: inbox_id_seq; Type: SEQUENCE SET; Schema: platform; Owner: -
--

SELECT pg_catalog.setval('platform.inbox_id_seq', 1, false);


--
-- Name: outbox_seq_seq; Type: SEQUENCE SET; Schema: platform; Owner: -
--

SELECT pg_catalog.setval('platform.outbox_seq_seq', 1, false);


--
-- Name: enforcement_cases pk_enforcement_cases; Type: CONSTRAINT; Schema: admin; Owner: -
--

ALTER TABLE ONLY admin.enforcement_cases
    ADD CONSTRAINT pk_enforcement_cases PRIMARY KEY (id);


--
-- Name: enforcement_cases uq_enforcement_cases_source_event_id; Type: CONSTRAINT; Schema: admin; Owner: -
--

ALTER TABLE ONLY admin.enforcement_cases
    ADD CONSTRAINT uq_enforcement_cases_source_event_id UNIQUE (source_event_id);


--
-- Name: inference_logs pk_inference_logs; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.inference_logs
    ADD CONSTRAINT pk_inference_logs PRIMARY KEY (id);


--
-- Name: prompt_versions pk_prompt_versions; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prompt_versions
    ADD CONSTRAINT pk_prompt_versions PRIMARY KEY (id);


--
-- Name: risk_observations pk_risk_observations; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.risk_observations
    ADD CONSTRAINT pk_risk_observations PRIMARY KEY (id);


--
-- Name: prompt_versions uq_prompt_versions_prompt_key_version; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prompt_versions
    ADD CONSTRAINT uq_prompt_versions_prompt_key_version UNIQUE (prompt_key, version);


--
-- Name: risk_observations uq_risk_observations_source_event_id; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.risk_observations
    ADD CONSTRAINT uq_risk_observations_source_event_id UNIQUE (source_event_id);


--
-- Name: event_facts pk_event_facts; Type: CONSTRAINT; Schema: analytics; Owner: -
--

ALTER TABLE ONLY analytics.event_facts
    ADD CONSTRAINT pk_event_facts PRIMARY KEY (id);


--
-- Name: event_facts uq_event_facts_seq; Type: CONSTRAINT; Schema: analytics; Owner: -
--

ALTER TABLE ONLY analytics.event_facts
    ADD CONSTRAINT uq_event_facts_seq UNIQUE (seq);


--
-- Name: event_facts uq_event_facts_source_event_id; Type: CONSTRAINT; Schema: analytics; Owner: -
--

ALTER TABLE ONLY analytics.event_facts
    ADD CONSTRAINT uq_event_facts_source_event_id UNIQUE (source_event_id);


--
-- Name: audit_records pk_audit_records; Type: CONSTRAINT; Schema: audit; Owner: -
--

ALTER TABLE ONLY audit.audit_records
    ADD CONSTRAINT pk_audit_records PRIMARY KEY (id);


--
-- Name: export_jobs pk_export_jobs; Type: CONSTRAINT; Schema: audit; Owner: -
--

ALTER TABLE ONLY audit.export_jobs
    ADD CONSTRAINT pk_export_jobs PRIMARY KEY (id);


--
-- Name: audit_records uq_audit_records_hash; Type: CONSTRAINT; Schema: audit; Owner: -
--

ALTER TABLE ONLY audit.audit_records
    ADD CONSTRAINT uq_audit_records_hash UNIQUE (hash);


--
-- Name: audit_records uq_audit_records_seq; Type: CONSTRAINT; Schema: audit; Owner: -
--

ALTER TABLE ONLY audit.audit_records
    ADD CONSTRAINT uq_audit_records_seq UNIQUE (seq);


--
-- Name: audit_records uq_audit_records_source_event_id; Type: CONSTRAINT; Schema: audit; Owner: -
--

ALTER TABLE ONLY audit.audit_records
    ADD CONSTRAINT uq_audit_records_source_event_id UNIQUE (source_event_id);


--
-- Name: billing_contacts pk_billing_contacts; Type: CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.billing_contacts
    ADD CONSTRAINT pk_billing_contacts PRIMARY KEY (id);


--
-- Name: business_units pk_business_units; Type: CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.business_units
    ADD CONSTRAINT pk_business_units PRIMARY KEY (id);


--
-- Name: cost_centers pk_cost_centers; Type: CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.cost_centers
    ADD CONSTRAINT pk_cost_centers PRIMARY KEY (id);


--
-- Name: invitations pk_invitations; Type: CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.invitations
    ADD CONSTRAINT pk_invitations PRIMARY KEY (id);


--
-- Name: members pk_members; Type: CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.members
    ADD CONSTRAINT pk_members PRIMARY KEY (id);


--
-- Name: organizations pk_organizations; Type: CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.organizations
    ADD CONSTRAINT pk_organizations PRIMARY KEY (id);


--
-- Name: billing_contacts uq_billing_contacts_organization_id_identity_id; Type: CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.billing_contacts
    ADD CONSTRAINT uq_billing_contacts_organization_id_identity_id UNIQUE (organization_id, identity_id);


--
-- Name: business_units uq_business_units_organization_id_name; Type: CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.business_units
    ADD CONSTRAINT uq_business_units_organization_id_name UNIQUE (organization_id, name);


--
-- Name: cost_centers uq_cost_centers_organization_id_code; Type: CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.cost_centers
    ADD CONSTRAINT uq_cost_centers_organization_id_code UNIQUE (organization_id, code);


--
-- Name: invitations uq_invitations_token_hash; Type: CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.invitations
    ADD CONSTRAINT uq_invitations_token_hash UNIQUE (token_hash);


--
-- Name: members uq_members_organization_id_identity_id; Type: CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.members
    ADD CONSTRAINT uq_members_organization_id_identity_id UNIQUE (organization_id, identity_id);


--
-- Name: change_orders pk_change_orders; Type: CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.change_orders
    ADD CONSTRAINT pk_change_orders PRIMARY KEY (id);


--
-- Name: contract_revisions pk_contract_revisions; Type: CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.contract_revisions
    ADD CONSTRAINT pk_contract_revisions PRIMARY KEY (id);


--
-- Name: contracts pk_contracts; Type: CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.contracts
    ADD CONSTRAINT pk_contracts PRIMARY KEY (id);


--
-- Name: milestones pk_milestones; Type: CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.milestones
    ADD CONSTRAINT pk_milestones PRIMARY KEY (id);


--
-- Name: signatures pk_signatures; Type: CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.signatures
    ADD CONSTRAINT pk_signatures PRIMARY KEY (id);


--
-- Name: submissions pk_submissions; Type: CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.submissions
    ADD CONSTRAINT pk_submissions PRIMARY KEY (id);


--
-- Name: contract_revisions uq_contract_revisions_change_order_id; Type: CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.contract_revisions
    ADD CONSTRAINT uq_contract_revisions_change_order_id UNIQUE (change_order_id);


--
-- Name: contract_revisions uq_contract_revisions_contract_id_contract_version; Type: CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.contract_revisions
    ADD CONSTRAINT uq_contract_revisions_contract_id_contract_version UNIQUE (contract_id, contract_version);


--
-- Name: contracts uq_contracts_proposal_id; Type: CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.contracts
    ADD CONSTRAINT uq_contracts_proposal_id UNIQUE (proposal_id);


--
-- Name: contracts uq_contracts_reference; Type: CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.contracts
    ADD CONSTRAINT uq_contracts_reference UNIQUE (reference);


--
-- Name: milestones uq_milestones_contract_id_sequence; Type: CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.milestones
    ADD CONSTRAINT uq_milestones_contract_id_sequence UNIQUE (contract_id, sequence);


--
-- Name: signatures uq_signatures_contract_id_contract_version_party; Type: CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.signatures
    ADD CONSTRAINT uq_signatures_contract_id_contract_version_party UNIQUE (contract_id, contract_version, party);


--
-- Name: appeals pk_appeals; Type: CONSTRAINT; Schema: dispute; Owner: -
--

ALTER TABLE ONLY dispute.appeals
    ADD CONSTRAINT pk_appeals PRIMARY KEY (id);


--
-- Name: cases pk_cases; Type: CONSTRAINT; Schema: dispute; Owner: -
--

ALTER TABLE ONLY dispute.cases
    ADD CONSTRAINT pk_cases PRIMARY KEY (id);


--
-- Name: evidence_items pk_evidence_items; Type: CONSTRAINT; Schema: dispute; Owner: -
--

ALTER TABLE ONLY dispute.evidence_items
    ADD CONSTRAINT pk_evidence_items PRIMARY KEY (id);


--
-- Name: resolution_proposals pk_resolution_proposals; Type: CONSTRAINT; Schema: dispute; Owner: -
--

ALTER TABLE ONLY dispute.resolution_proposals
    ADD CONSTRAINT pk_resolution_proposals PRIMARY KEY (id);


--
-- Name: timeline pk_timeline; Type: CONSTRAINT; Schema: dispute; Owner: -
--

ALTER TABLE ONLY dispute.timeline
    ADD CONSTRAINT pk_timeline PRIMARY KEY (id);


--
-- Name: appeals uq_appeals_case_id; Type: CONSTRAINT; Schema: dispute; Owner: -
--

ALTER TABLE ONLY dispute.appeals
    ADD CONSTRAINT uq_appeals_case_id UNIQUE (case_id);


--
-- Name: cases uq_cases_reference; Type: CONSTRAINT; Schema: dispute; Owner: -
--

ALTER TABLE ONLY dispute.cases
    ADD CONSTRAINT uq_cases_reference UNIQUE (reference);


--
-- Name: accounts pk_accounts; Type: CONSTRAINT; Schema: escrow; Owner: -
--

ALTER TABLE ONLY escrow.accounts
    ADD CONSTRAINT pk_accounts PRIMARY KEY (id);


--
-- Name: allocations pk_allocations; Type: CONSTRAINT; Schema: escrow; Owner: -
--

ALTER TABLE ONLY escrow.allocations
    ADD CONSTRAINT pk_allocations PRIMARY KEY (id);


--
-- Name: fundings pk_fundings; Type: CONSTRAINT; Schema: escrow; Owner: -
--

ALTER TABLE ONLY escrow.fundings
    ADD CONSTRAINT pk_fundings PRIMARY KEY (id);


--
-- Name: ledger_entries pk_ledger_entries; Type: CONSTRAINT; Schema: escrow; Owner: -
--

ALTER TABLE ONLY escrow.ledger_entries
    ADD CONSTRAINT pk_ledger_entries PRIMARY KEY (id);


--
-- Name: releases pk_releases; Type: CONSTRAINT; Schema: escrow; Owner: -
--

ALTER TABLE ONLY escrow.releases
    ADD CONSTRAINT pk_releases PRIMARY KEY (id);


--
-- Name: accounts uq_accounts_contract_id; Type: CONSTRAINT; Schema: escrow; Owner: -
--

ALTER TABLE ONLY escrow.accounts
    ADD CONSTRAINT uq_accounts_contract_id UNIQUE (contract_id);


--
-- Name: allocations uq_allocations_milestone_id; Type: CONSTRAINT; Schema: escrow; Owner: -
--

ALTER TABLE ONLY escrow.allocations
    ADD CONSTRAINT uq_allocations_milestone_id UNIQUE (milestone_id);


--
-- Name: releases uq_releases_milestone_id; Type: CONSTRAINT; Schema: escrow; Owner: -
--

ALTER TABLE ONLY escrow.releases
    ADD CONSTRAINT uq_releases_milestone_id UNIQUE (milestone_id);


--
-- Name: firms pk_firms; Type: CONSTRAINT; Schema: firm; Owner: -
--

ALTER TABLE ONLY firm.firms
    ADD CONSTRAINT pk_firms PRIMARY KEY (id);


--
-- Name: invitations pk_invitations; Type: CONSTRAINT; Schema: firm; Owner: -
--

ALTER TABLE ONLY firm.invitations
    ADD CONSTRAINT pk_invitations PRIMARY KEY (id);


--
-- Name: members pk_members; Type: CONSTRAINT; Schema: firm; Owner: -
--

ALTER TABLE ONLY firm.members
    ADD CONSTRAINT pk_members PRIMARY KEY (id);


--
-- Name: invitations uq_invitations_token_hash; Type: CONSTRAINT; Schema: firm; Owner: -
--

ALTER TABLE ONLY firm.invitations
    ADD CONSTRAINT uq_invitations_token_hash UNIQUE (token_hash);


--
-- Name: members uq_members_firm_id_identity_id; Type: CONSTRAINT; Schema: firm; Owner: -
--

ALTER TABLE ONLY firm.members
    ADD CONSTRAINT uq_members_firm_id_identity_id UNIQUE (firm_id, identity_id);


--
-- Name: consent_records pk_consent_records; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.consent_records
    ADD CONSTRAINT pk_consent_records PRIMARY KEY (id);


--
-- Name: data_requests pk_data_requests; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.data_requests
    ADD CONSTRAINT pk_data_requests PRIMARY KEY (id);


--
-- Name: duplicate_suspicions pk_duplicate_suspicions; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.duplicate_suspicions
    ADD CONSTRAINT pk_duplicate_suspicions PRIMARY KEY (id);


--
-- Name: identities pk_identities; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.identities
    ADD CONSTRAINT pk_identities PRIMARY KEY (id);


--
-- Name: identity_links pk_identity_links; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.identity_links
    ADD CONSTRAINT pk_identity_links PRIMARY KEY (id);


--
-- Name: sessions pk_sessions; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.sessions
    ADD CONSTRAINT pk_sessions PRIMARY KEY (id);


--
-- Name: duplicate_suspicions uq_duplicate_pair; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.duplicate_suspicions
    ADD CONSTRAINT uq_duplicate_pair UNIQUE (identity_id, other_identity_id);


--
-- Name: identities uq_identities_email; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.identities
    ADD CONSTRAINT uq_identities_email UNIQUE (email);


--
-- Name: identity_links uq_identity_links_identity_id_link_type_target_id; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.identity_links
    ADD CONSTRAINT uq_identity_links_identity_id_link_type_target_id UNIQUE (identity_id, link_type, target_id);


--
-- Name: sessions uq_sessions_refresh_token_hash; Type: CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.sessions
    ADD CONSTRAINT uq_sessions_refresh_token_hash UNIQUE (refresh_token_hash);


--
-- Name: collection_items pk_collection_items; Type: CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.collection_items
    ADD CONSTRAINT pk_collection_items PRIMARY KEY (id);


--
-- Name: collections pk_collections; Type: CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.collections
    ADD CONSTRAINT pk_collections PRIMARY KEY (id);


--
-- Name: saved_professionals pk_saved_professionals; Type: CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.saved_professionals
    ADD CONSTRAINT pk_saved_professionals PRIMARY KEY (id);


--
-- Name: saved_searches pk_saved_searches; Type: CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.saved_searches
    ADD CONSTRAINT pk_saved_searches PRIMARY KEY (id);


--
-- Name: specialization_suggestions pk_specialization_suggestions; Type: CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.specialization_suggestions
    ADD CONSTRAINT pk_specialization_suggestions PRIMARY KEY (id);


--
-- Name: taxonomy_nodes pk_taxonomy_nodes; Type: CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.taxonomy_nodes
    ADD CONSTRAINT pk_taxonomy_nodes PRIMARY KEY (id);


--
-- Name: collection_items uq_collection_items_collection_id_professional_id; Type: CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.collection_items
    ADD CONSTRAINT uq_collection_items_collection_id_professional_id UNIQUE (collection_id, professional_id);


--
-- Name: collections uq_collections_identity_id_name; Type: CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.collections
    ADD CONSTRAINT uq_collections_identity_id_name UNIQUE (identity_id, name);


--
-- Name: saved_professionals uq_saved_professionals_identity_id_professional_id; Type: CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.saved_professionals
    ADD CONSTRAINT uq_saved_professionals_identity_id_professional_id UNIQUE (identity_id, professional_id);


--
-- Name: saved_searches uq_saved_searches_identity_id_name; Type: CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.saved_searches
    ADD CONSTRAINT uq_saved_searches_identity_id_name UNIQUE (identity_id, name);


--
-- Name: taxonomy_nodes uq_taxonomy_nodes_slug; Type: CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.taxonomy_nodes
    ADD CONSTRAINT uq_taxonomy_nodes_slug UNIQUE (slug);


--
-- Name: attachments pk_attachments; Type: CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.attachments
    ADD CONSTRAINT pk_attachments PRIMARY KEY (id);


--
-- Name: dispute_contexts pk_dispute_contexts; Type: CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.dispute_contexts
    ADD CONSTRAINT pk_dispute_contexts PRIMARY KEY (dispute_id);


--
-- Name: messages pk_messages; Type: CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.messages
    ADD CONSTRAINT pk_messages PRIMARY KEY (id);


--
-- Name: read_positions pk_read_positions; Type: CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.read_positions
    ADD CONSTRAINT pk_read_positions PRIMARY KEY (id);


--
-- Name: threads pk_threads; Type: CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.threads
    ADD CONSTRAINT pk_threads PRIMARY KEY (id);


--
-- Name: attachments uq_attachments_thread_id_name_file_version; Type: CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.attachments
    ADD CONSTRAINT uq_attachments_thread_id_name_file_version UNIQUE (thread_id, name, file_version);


--
-- Name: messages uq_messages_thread_id_sequence; Type: CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.messages
    ADD CONSTRAINT uq_messages_thread_id_sequence UNIQUE (thread_id, sequence);


--
-- Name: messages uq_messages_thread_id_source_event_id; Type: CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.messages
    ADD CONSTRAINT uq_messages_thread_id_source_event_id UNIQUE (thread_id, source_event_id);


--
-- Name: read_positions uq_read_positions_thread_id_identity_id; Type: CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.read_positions
    ADD CONSTRAINT uq_read_positions_thread_id_identity_id UNIQUE (thread_id, identity_id);


--
-- Name: threads uq_threads_context_type_context_id; Type: CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.threads
    ADD CONSTRAINT uq_threads_context_type_context_id UNIQUE (context_type, context_id);


--
-- Name: delivery_attempts pk_delivery_attempts; Type: CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.delivery_attempts
    ADD CONSTRAINT pk_delivery_attempts PRIMARY KEY (id);


--
-- Name: notifications pk_notifications; Type: CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.notifications
    ADD CONSTRAINT pk_notifications PRIMARY KEY (id);


--
-- Name: preferences pk_preferences; Type: CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.preferences
    ADD CONSTRAINT pk_preferences PRIMARY KEY (id);


--
-- Name: webhook_deliveries pk_webhook_deliveries; Type: CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.webhook_deliveries
    ADD CONSTRAINT pk_webhook_deliveries PRIMARY KEY (id);


--
-- Name: webhook_endpoints pk_webhook_endpoints; Type: CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.webhook_endpoints
    ADD CONSTRAINT pk_webhook_endpoints PRIMARY KEY (id);


--
-- Name: notifications uq_notifications_source_event_id_identity_id; Type: CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.notifications
    ADD CONSTRAINT uq_notifications_source_event_id_identity_id UNIQUE (source_event_id, identity_id);


--
-- Name: preferences uq_preferences_identity_id; Type: CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.preferences
    ADD CONSTRAINT uq_preferences_identity_id UNIQUE (identity_id);


--
-- Name: webhook_deliveries uq_webhook_deliveries_endpoint_id_source_event_id; Type: CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.webhook_deliveries
    ADD CONSTRAINT uq_webhook_deliveries_endpoint_id_source_event_id UNIQUE (endpoint_id, source_event_id);


--
-- Name: invoices pk_invoices; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.invoices
    ADD CONSTRAINT pk_invoices PRIMARY KEY (id);


--
-- Name: payment_intents pk_payment_intents; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.payment_intents
    ADD CONSTRAINT pk_payment_intents PRIMARY KEY (id);


--
-- Name: payout_accounts pk_payout_accounts; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.payout_accounts
    ADD CONSTRAINT pk_payout_accounts PRIMARY KEY (id);


--
-- Name: payouts pk_payouts; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.payouts
    ADD CONSTRAINT pk_payouts PRIMARY KEY (id);


--
-- Name: reconciliation_batches pk_reconciliation_batches; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.reconciliation_batches
    ADD CONSTRAINT pk_reconciliation_batches PRIMARY KEY (id);


--
-- Name: refunds pk_refunds; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.refunds
    ADD CONSTRAINT pk_refunds PRIMARY KEY (id);


--
-- Name: webhook_events pk_webhook_events; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.webhook_events
    ADD CONSTRAINT pk_webhook_events PRIMARY KEY (id);


--
-- Name: invoices uq_invoices_number; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.invoices
    ADD CONSTRAINT uq_invoices_number UNIQUE (number);


--
-- Name: invoices uq_invoices_release_id; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.invoices
    ADD CONSTRAINT uq_invoices_release_id UNIQUE (release_id);


--
-- Name: payment_intents uq_payment_intents_funding_id; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.payment_intents
    ADD CONSTRAINT uq_payment_intents_funding_id UNIQUE (funding_id);


--
-- Name: payout_accounts uq_payout_accounts_professional_id; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.payout_accounts
    ADD CONSTRAINT uq_payout_accounts_professional_id UNIQUE (professional_id);


--
-- Name: payouts uq_payouts_release_id; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.payouts
    ADD CONSTRAINT uq_payouts_release_id UNIQUE (release_id);


--
-- Name: reconciliation_batches uq_reconciliation_batches_day; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.reconciliation_batches
    ADD CONSTRAINT uq_reconciliation_batches_day UNIQUE (day);


--
-- Name: refunds uq_refunds_escrow_refund_id; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.refunds
    ADD CONSTRAINT uq_refunds_escrow_refund_id UNIQUE (escrow_refund_id);


--
-- Name: webhook_events uq_webhook_provider_event; Type: CONSTRAINT; Schema: payments; Owner: -
--

ALTER TABLE ONLY payments.webhook_events
    ADD CONSTRAINT uq_webhook_provider_event UNIQUE (provider, event_id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: consumer_failures pk_consumer_failures; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.consumer_failures
    ADD CONSTRAINT pk_consumer_failures PRIMARY KEY (id);


--
-- Name: idempotency_keys pk_idempotency_keys; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.idempotency_keys
    ADD CONSTRAINT pk_idempotency_keys PRIMARY KEY (scope);


--
-- Name: inbox pk_inbox; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.inbox
    ADD CONSTRAINT pk_inbox PRIMARY KEY (id);


--
-- Name: outbox pk_outbox; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.outbox
    ADD CONSTRAINT pk_outbox PRIMARY KEY (seq);


--
-- Name: timers pk_timers; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.timers
    ADD CONSTRAINT pk_timers PRIMARY KEY (id);


--
-- Name: consumer_failures uq_consumer_failures_consumer_event_id; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.consumer_failures
    ADD CONSTRAINT uq_consumer_failures_consumer_event_id UNIQUE (consumer, event_id);


--
-- Name: inbox uq_inbox_consumer_event_id; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.inbox
    ADD CONSTRAINT uq_inbox_consumer_event_id UNIQUE (consumer, event_id);


--
-- Name: outbox uq_outbox_event_id; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.outbox
    ADD CONSTRAINT uq_outbox_event_id UNIQUE (event_id);


--
-- Name: timers uq_timers_kind_key; Type: CONSTRAINT; Schema: platform; Owner: -
--

ALTER TABLE ONLY platform.timers
    ADD CONSTRAINT uq_timers_kind_key UNIQUE (kind, key);


--
-- Name: approval_requests pk_approval_requests; Type: CONSTRAINT; Schema: policy; Owner: -
--

ALTER TABLE ONLY policy.approval_requests
    ADD CONSTRAINT pk_approval_requests PRIMARY KEY (id);


--
-- Name: approval_votes pk_approval_votes; Type: CONSTRAINT; Schema: policy; Owner: -
--

ALTER TABLE ONLY policy.approval_votes
    ADD CONSTRAINT pk_approval_votes PRIMARY KEY (id);


--
-- Name: exception_requests pk_exception_requests; Type: CONSTRAINT; Schema: policy; Owner: -
--

ALTER TABLE ONLY policy.exception_requests
    ADD CONSTRAINT pk_exception_requests PRIMARY KEY (id);


--
-- Name: policy_evaluations pk_policy_evaluations; Type: CONSTRAINT; Schema: policy; Owner: -
--

ALTER TABLE ONLY policy.policy_evaluations
    ADD CONSTRAINT pk_policy_evaluations PRIMARY KEY (id);


--
-- Name: profiles pk_profiles; Type: CONSTRAINT; Schema: policy; Owner: -
--

ALTER TABLE ONLY policy.profiles
    ADD CONSTRAINT pk_profiles PRIMARY KEY (id);


--
-- Name: versions pk_versions; Type: CONSTRAINT; Schema: policy; Owner: -
--

ALTER TABLE ONLY policy.versions
    ADD CONSTRAINT pk_versions PRIMARY KEY (id);


--
-- Name: approval_requests uq_policy_approval_request_key; Type: CONSTRAINT; Schema: policy; Owner: -
--

ALTER TABLE ONLY policy.approval_requests
    ADD CONSTRAINT uq_policy_approval_request_key UNIQUE (request_key);


--
-- Name: approval_votes uq_policy_approval_vote; Type: CONSTRAINT; Schema: policy; Owner: -
--

ALTER TABLE ONLY policy.approval_votes
    ADD CONSTRAINT uq_policy_approval_vote UNIQUE (request_id, identity_id);


--
-- Name: versions uq_policy_version_number; Type: CONSTRAINT; Schema: policy; Owner: -
--

ALTER TABLE ONLY policy.versions
    ADD CONSTRAINT uq_policy_version_number UNIQUE (profile_id, number);


--
-- Name: credential_claims pk_credential_claims; Type: CONSTRAINT; Schema: professional; Owner: -
--

ALTER TABLE ONLY professional.credential_claims
    ADD CONSTRAINT pk_credential_claims PRIMARY KEY (id);


--
-- Name: offerings pk_offerings; Type: CONSTRAINT; Schema: professional; Owner: -
--

ALTER TABLE ONLY professional.offerings
    ADD CONSTRAINT pk_offerings PRIMARY KEY (id);


--
-- Name: professionals pk_professionals; Type: CONSTRAINT; Schema: professional; Owner: -
--

ALTER TABLE ONLY professional.professionals
    ADD CONSTRAINT pk_professionals PRIMARY KEY (id);


--
-- Name: saved_buyers pk_saved_buyers; Type: CONSTRAINT; Schema: professional; Owner: -
--

ALTER TABLE ONLY professional.saved_buyers
    ADD CONSTRAINT pk_saved_buyers PRIMARY KEY (id);


--
-- Name: professionals uq_professionals_identity_id; Type: CONSTRAINT; Schema: professional; Owner: -
--

ALTER TABLE ONLY professional.professionals
    ADD CONSTRAINT uq_professionals_identity_id UNIQUE (identity_id);


--
-- Name: saved_buyers uq_saved_buyers_professional_id_organization_id; Type: CONSTRAINT; Schema: professional; Owner: -
--

ALTER TABLE ONLY professional.saved_buyers
    ADD CONSTRAINT uq_saved_buyers_professional_id_organization_id UNIQUE (professional_id, organization_id);


--
-- Name: proposals pk_proposals; Type: CONSTRAINT; Schema: proposal; Owner: -
--

ALTER TABLE ONLY proposal.proposals
    ADD CONSTRAINT pk_proposals PRIMARY KEY (id);


--
-- Name: requests pk_requests; Type: CONSTRAINT; Schema: proposal; Owner: -
--

ALTER TABLE ONLY proposal.requests
    ADD CONSTRAINT pk_requests PRIMARY KEY (id);


--
-- Name: proposals uq_proposals_request_id; Type: CONSTRAINT; Schema: proposal; Owner: -
--

ALTER TABLE ONLY proposal.proposals
    ADD CONSTRAINT uq_proposals_request_id UNIQUE (request_id);


--
-- Name: reviews pk_reviews; Type: CONSTRAINT; Schema: review; Owner: -
--

ALTER TABLE ONLY review.reviews
    ADD CONSTRAINT pk_reviews PRIMARY KEY (id);


--
-- Name: reviews uq_reviews_contract_id; Type: CONSTRAINT; Schema: review; Owner: -
--

ALTER TABLE ONLY review.reviews
    ADD CONSTRAINT uq_reviews_contract_id UNIQUE (contract_id);


--
-- Name: professional_documents pk_professional_documents; Type: CONSTRAINT; Schema: search; Owner: -
--

ALTER TABLE ONLY search.professional_documents
    ADD CONSTRAINT pk_professional_documents PRIMARY KEY (id);


--
-- Name: professional_documents uq_professional_documents_professional_id; Type: CONSTRAINT; Schema: search; Owner: -
--

ALTER TABLE ONLY search.professional_documents
    ADD CONSTRAINT uq_professional_documents_professional_id UNIQUE (professional_id);


--
-- Name: profiles pk_profiles; Type: CONSTRAINT; Schema: trust; Owner: -
--

ALTER TABLE ONLY trust.profiles
    ADD CONSTRAINT pk_profiles PRIMARY KEY (id);


--
-- Name: signals pk_signals; Type: CONSTRAINT; Schema: trust; Owner: -
--

ALTER TABLE ONLY trust.signals
    ADD CONSTRAINT pk_signals PRIMARY KEY (id);


--
-- Name: tier_history pk_tier_history; Type: CONSTRAINT; Schema: trust; Owner: -
--

ALTER TABLE ONLY trust.tier_history
    ADD CONSTRAINT pk_tier_history PRIMARY KEY (id);


--
-- Name: profiles uq_profiles_professional_id; Type: CONSTRAINT; Schema: trust; Owner: -
--

ALTER TABLE ONLY trust.profiles
    ADD CONSTRAINT uq_profiles_professional_id UNIQUE (professional_id);


--
-- Name: signals uq_signals_professional_id_source_event_id; Type: CONSTRAINT; Schema: trust; Owner: -
--

ALTER TABLE ONLY trust.signals
    ADD CONSTRAINT uq_signals_professional_id_source_event_id UNIQUE (professional_id, source_event_id);


--
-- Name: appeals pk_appeals; Type: CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.appeals
    ADD CONSTRAINT pk_appeals PRIMARY KEY (id);


--
-- Name: cases pk_cases; Type: CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.cases
    ADD CONSTRAINT pk_cases PRIMARY KEY (id);


--
-- Name: evidence_checks pk_evidence_checks; Type: CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.evidence_checks
    ADD CONSTRAINT pk_evidence_checks PRIMARY KEY (id);


--
-- Name: evidence_items pk_evidence_items; Type: CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.evidence_items
    ADD CONSTRAINT pk_evidence_items PRIMARY KEY (id);


--
-- Name: provider_events pk_provider_events; Type: CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.provider_events
    ADD CONSTRAINT pk_provider_events PRIMARY KEY (id);


--
-- Name: provider_sessions pk_provider_sessions; Type: CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.provider_sessions
    ADD CONSTRAINT pk_provider_sessions PRIMARY KEY (id);


--
-- Name: appeals uq_appeals_case_id; Type: CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.appeals
    ADD CONSTRAINT uq_appeals_case_id UNIQUE (case_id);


--
-- Name: cases uq_cases_credential_claim_id; Type: CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.cases
    ADD CONSTRAINT uq_cases_credential_claim_id UNIQUE (credential_claim_id);


--
-- Name: evidence_checks uq_evidence_checks_evidence_id; Type: CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.evidence_checks
    ADD CONSTRAINT uq_evidence_checks_evidence_id UNIQUE (evidence_id);


--
-- Name: provider_events uq_provider_events_event_id; Type: CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.provider_events
    ADD CONSTRAINT uq_provider_events_event_id UNIQUE (event_id);


--
-- Name: provider_sessions uq_provider_sessions_case_id; Type: CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.provider_sessions
    ADD CONSTRAINT uq_provider_sessions_case_id UNIQUE (case_id);


--
-- Name: provider_sessions uq_provider_sessions_provider_ref; Type: CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.provider_sessions
    ADD CONSTRAINT uq_provider_sessions_provider_ref UNIQUE (provider_ref);


--
-- Name: ix_admin_enforcement_cases_subject_id; Type: INDEX; Schema: admin; Owner: -
--

CREATE INDEX ix_admin_enforcement_cases_subject_id ON admin.enforcement_cases USING btree (subject_id);


--
-- Name: ix_ai_risk_observations_identity_id; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX ix_ai_risk_observations_identity_id ON ai.risk_observations USING btree (identity_id);


--
-- Name: ix_analytics_event_facts_organization_id; Type: INDEX; Schema: analytics; Owner: -
--

CREATE INDEX ix_analytics_event_facts_organization_id ON analytics.event_facts USING btree (organization_id);


--
-- Name: ix_analytics_event_facts_professional_id; Type: INDEX; Schema: analytics; Owner: -
--

CREATE INDEX ix_analytics_event_facts_professional_id ON analytics.event_facts USING btree (professional_id);


--
-- Name: ix_audit_correlation; Type: INDEX; Schema: audit; Owner: -
--

CREATE INDEX ix_audit_correlation ON audit.audit_records USING btree (correlation_id);


--
-- Name: ix_audit_object; Type: INDEX; Schema: audit; Owner: -
--

CREATE INDEX ix_audit_object ON audit.audit_records USING btree (object_type, object_id);


--
-- Name: ix_audit_tenant_time; Type: INDEX; Schema: audit; Owner: -
--

CREATE INDEX ix_audit_tenant_time ON audit.audit_records USING btree (tenant_id, occurred_at);


--
-- Name: ix_buyer_billing_contacts_organization_id; Type: INDEX; Schema: buyer; Owner: -
--

CREATE INDEX ix_buyer_billing_contacts_organization_id ON buyer.billing_contacts USING btree (organization_id);


--
-- Name: ix_buyer_business_units_organization_id; Type: INDEX; Schema: buyer; Owner: -
--

CREATE INDEX ix_buyer_business_units_organization_id ON buyer.business_units USING btree (organization_id);


--
-- Name: ix_buyer_cost_centers_organization_id; Type: INDEX; Schema: buyer; Owner: -
--

CREATE INDEX ix_buyer_cost_centers_organization_id ON buyer.cost_centers USING btree (organization_id);


--
-- Name: ix_buyer_invitations_organization_id; Type: INDEX; Schema: buyer; Owner: -
--

CREATE INDEX ix_buyer_invitations_organization_id ON buyer.invitations USING btree (organization_id);


--
-- Name: ix_buyer_members_identity_id; Type: INDEX; Schema: buyer; Owner: -
--

CREATE INDEX ix_buyer_members_identity_id ON buyer.members USING btree (identity_id);


--
-- Name: ix_buyer_members_organization_id; Type: INDEX; Schema: buyer; Owner: -
--

CREATE INDEX ix_buyer_members_organization_id ON buyer.members USING btree (organization_id);


--
-- Name: ix_buyer_organizations_created_by; Type: INDEX; Schema: buyer; Owner: -
--

CREATE INDEX ix_buyer_organizations_created_by ON buyer.organizations USING btree (created_by);


--
-- Name: ix_invitations_pending_email; Type: INDEX; Schema: buyer; Owner: -
--

CREATE INDEX ix_invitations_pending_email ON buyer.invitations USING btree (email) WHERE ((status)::text = 'PENDING'::text);


--
-- Name: ix_change_orders_contract; Type: INDEX; Schema: contract; Owner: -
--

CREATE INDEX ix_change_orders_contract ON contract.change_orders USING btree (contract_id, created_at);


--
-- Name: ix_contract_contract_revisions_contract_id; Type: INDEX; Schema: contract; Owner: -
--

CREATE INDEX ix_contract_contract_revisions_contract_id ON contract.contract_revisions USING btree (contract_id);


--
-- Name: ix_contract_milestones_contract_id; Type: INDEX; Schema: contract; Owner: -
--

CREATE INDEX ix_contract_milestones_contract_id ON contract.milestones USING btree (contract_id);


--
-- Name: ix_contract_signatures_contract_id; Type: INDEX; Schema: contract; Owner: -
--

CREATE INDEX ix_contract_signatures_contract_id ON contract.signatures USING btree (contract_id);


--
-- Name: ix_contract_submissions_milestone_id; Type: INDEX; Schema: contract; Owner: -
--

CREATE INDEX ix_contract_submissions_milestone_id ON contract.submissions USING btree (milestone_id);


--
-- Name: ix_contracts_org; Type: INDEX; Schema: contract; Owner: -
--

CREATE INDEX ix_contracts_org ON contract.contracts USING btree (organization_id, created_at);


--
-- Name: ix_contracts_professional; Type: INDEX; Schema: contract; Owner: -
--

CREATE INDEX ix_contracts_professional ON contract.contracts USING btree (professional_id, created_at);


--
-- Name: ix_dispute_cases_contract; Type: INDEX; Schema: dispute; Owner: -
--

CREATE INDEX ix_dispute_cases_contract ON dispute.cases USING btree (contract_id, status);


--
-- Name: ix_dispute_cases_organization_id; Type: INDEX; Schema: dispute; Owner: -
--

CREATE INDEX ix_dispute_cases_organization_id ON dispute.cases USING btree (organization_id);


--
-- Name: ix_dispute_cases_professional_id; Type: INDEX; Schema: dispute; Owner: -
--

CREATE INDEX ix_dispute_cases_professional_id ON dispute.cases USING btree (professional_id);


--
-- Name: ix_dispute_evidence_items_case_id; Type: INDEX; Schema: dispute; Owner: -
--

CREATE INDEX ix_dispute_evidence_items_case_id ON dispute.evidence_items USING btree (case_id);


--
-- Name: ix_dispute_resolution_proposals_case_id; Type: INDEX; Schema: dispute; Owner: -
--

CREATE INDEX ix_dispute_resolution_proposals_case_id ON dispute.resolution_proposals USING btree (case_id);


--
-- Name: ix_dispute_timeline_case_id; Type: INDEX; Schema: dispute; Owner: -
--

CREATE INDEX ix_dispute_timeline_case_id ON dispute.timeline USING btree (case_id);


--
-- Name: ix_escrow_accounts_organization_id; Type: INDEX; Schema: escrow; Owner: -
--

CREATE INDEX ix_escrow_accounts_organization_id ON escrow.accounts USING btree (organization_id);


--
-- Name: ix_escrow_accounts_professional_id; Type: INDEX; Schema: escrow; Owner: -
--

CREATE INDEX ix_escrow_accounts_professional_id ON escrow.accounts USING btree (professional_id);


--
-- Name: ix_escrow_allocations_account_id; Type: INDEX; Schema: escrow; Owner: -
--

CREATE INDEX ix_escrow_allocations_account_id ON escrow.allocations USING btree (account_id);


--
-- Name: ix_escrow_releases_account_id; Type: INDEX; Schema: escrow; Owner: -
--

CREATE INDEX ix_escrow_releases_account_id ON escrow.releases USING btree (account_id);


--
-- Name: ix_fundings_account; Type: INDEX; Schema: escrow; Owner: -
--

CREATE INDEX ix_fundings_account ON escrow.fundings USING btree (account_id, created_at);


--
-- Name: ix_ledger_account; Type: INDEX; Schema: escrow; Owner: -
--

CREATE INDEX ix_ledger_account ON escrow.ledger_entries USING btree (account_id, created_at);


--
-- Name: ix_ledger_group; Type: INDEX; Schema: escrow; Owner: -
--

CREATE INDEX ix_ledger_group ON escrow.ledger_entries USING btree (entry_group_id);


--
-- Name: ix_firm_firms_created_by; Type: INDEX; Schema: firm; Owner: -
--

CREATE INDEX ix_firm_firms_created_by ON firm.firms USING btree (created_by);


--
-- Name: ix_firm_invitations_firm_id; Type: INDEX; Schema: firm; Owner: -
--

CREATE INDEX ix_firm_invitations_firm_id ON firm.invitations USING btree (firm_id);


--
-- Name: ix_firm_invitations_pending_email; Type: INDEX; Schema: firm; Owner: -
--

CREATE INDEX ix_firm_invitations_pending_email ON firm.invitations USING btree (email) WHERE ((status)::text = 'PENDING'::text);


--
-- Name: ix_firm_members_firm_id; Type: INDEX; Schema: firm; Owner: -
--

CREATE INDEX ix_firm_members_firm_id ON firm.members USING btree (firm_id);


--
-- Name: ix_firm_members_identity_id; Type: INDEX; Schema: firm; Owner: -
--

CREATE INDEX ix_firm_members_identity_id ON firm.members USING btree (identity_id);


--
-- Name: ix_identity_consent_records_identity_id; Type: INDEX; Schema: identity; Owner: -
--

CREATE INDEX ix_identity_consent_records_identity_id ON identity.consent_records USING btree (identity_id);


--
-- Name: ix_identity_data_requests_identity_id; Type: INDEX; Schema: identity; Owner: -
--

CREATE INDEX ix_identity_data_requests_identity_id ON identity.data_requests USING btree (identity_id);


--
-- Name: ix_identity_duplicate_suspicions_identity_id; Type: INDEX; Schema: identity; Owner: -
--

CREATE INDEX ix_identity_duplicate_suspicions_identity_id ON identity.duplicate_suspicions USING btree (identity_id);


--
-- Name: ix_identity_duplicate_suspicions_other_identity_id; Type: INDEX; Schema: identity; Owner: -
--

CREATE INDEX ix_identity_duplicate_suspicions_other_identity_id ON identity.duplicate_suspicions USING btree (other_identity_id);


--
-- Name: ix_identity_identity_links_identity_id; Type: INDEX; Schema: identity; Owner: -
--

CREATE INDEX ix_identity_identity_links_identity_id ON identity.identity_links USING btree (identity_id);


--
-- Name: ix_identity_sessions_family_id; Type: INDEX; Schema: identity; Owner: -
--

CREATE INDEX ix_identity_sessions_family_id ON identity.sessions USING btree (family_id);


--
-- Name: ix_identity_sessions_identity_id; Type: INDEX; Schema: identity; Owner: -
--

CREATE INDEX ix_identity_sessions_identity_id ON identity.sessions USING btree (identity_id);


--
-- Name: ix_marketplace_collection_items_collection_id; Type: INDEX; Schema: marketplace; Owner: -
--

CREATE INDEX ix_marketplace_collection_items_collection_id ON marketplace.collection_items USING btree (collection_id);


--
-- Name: ix_marketplace_collection_items_professional_id; Type: INDEX; Schema: marketplace; Owner: -
--

CREATE INDEX ix_marketplace_collection_items_professional_id ON marketplace.collection_items USING btree (professional_id);


--
-- Name: ix_marketplace_collections_identity_id; Type: INDEX; Schema: marketplace; Owner: -
--

CREATE INDEX ix_marketplace_collections_identity_id ON marketplace.collections USING btree (identity_id);


--
-- Name: ix_marketplace_saved_professionals_identity_id; Type: INDEX; Schema: marketplace; Owner: -
--

CREATE INDEX ix_marketplace_saved_professionals_identity_id ON marketplace.saved_professionals USING btree (identity_id);


--
-- Name: ix_marketplace_saved_professionals_professional_id; Type: INDEX; Schema: marketplace; Owner: -
--

CREATE INDEX ix_marketplace_saved_professionals_professional_id ON marketplace.saved_professionals USING btree (professional_id);


--
-- Name: ix_marketplace_saved_searches_identity_id; Type: INDEX; Schema: marketplace; Owner: -
--

CREATE INDEX ix_marketplace_saved_searches_identity_id ON marketplace.saved_searches USING btree (identity_id);


--
-- Name: ix_marketplace_specialization_suggestions_identity_id; Type: INDEX; Schema: marketplace; Owner: -
--

CREATE INDEX ix_marketplace_specialization_suggestions_identity_id ON marketplace.specialization_suggestions USING btree (identity_id);


--
-- Name: ix_marketplace_specialization_suggestions_professional_id; Type: INDEX; Schema: marketplace; Owner: -
--

CREATE INDEX ix_marketplace_specialization_suggestions_professional_id ON marketplace.specialization_suggestions USING btree (professional_id);


--
-- Name: ix_marketplace_taxonomy_nodes_category_slug; Type: INDEX; Schema: marketplace; Owner: -
--

CREATE INDEX ix_marketplace_taxonomy_nodes_category_slug ON marketplace.taxonomy_nodes USING btree (category_slug);


--
-- Name: ix_messages_thread_created; Type: INDEX; Schema: messaging; Owner: -
--

CREATE INDEX ix_messages_thread_created ON messaging.messages USING btree (thread_id, created_at);


--
-- Name: ix_messaging_attachments_thread_id; Type: INDEX; Schema: messaging; Owner: -
--

CREATE INDEX ix_messaging_attachments_thread_id ON messaging.attachments USING btree (thread_id);


--
-- Name: ix_messaging_dispute_contract_open; Type: INDEX; Schema: messaging; Owner: -
--

CREATE INDEX ix_messaging_dispute_contract_open ON messaging.dispute_contexts USING btree (contract_id, is_open);


--
-- Name: ix_messaging_threads_organization_id; Type: INDEX; Schema: messaging; Owner: -
--

CREATE INDEX ix_messaging_threads_organization_id ON messaging.threads USING btree (organization_id);


--
-- Name: ix_messaging_threads_professional_id; Type: INDEX; Schema: messaging; Owner: -
--

CREATE INDEX ix_messaging_threads_professional_id ON messaging.threads USING btree (professional_id);


--
-- Name: ix_notification_delivery_attempts_delivery_id; Type: INDEX; Schema: notification; Owner: -
--

CREATE INDEX ix_notification_delivery_attempts_delivery_id ON notification.delivery_attempts USING btree (delivery_id);


--
-- Name: ix_notification_webhook_endpoints_organization_id; Type: INDEX; Schema: notification; Owner: -
--

CREATE INDEX ix_notification_webhook_endpoints_organization_id ON notification.webhook_endpoints USING btree (organization_id);


--
-- Name: ix_notifications_recipient; Type: INDEX; Schema: notification; Owner: -
--

CREATE INDEX ix_notifications_recipient ON notification.notifications USING btree (identity_id, created_at);


--
-- Name: ix_invoices_org; Type: INDEX; Schema: payments; Owner: -
--

CREATE INDEX ix_invoices_org ON payments.invoices USING btree (organization_id, created_at);


--
-- Name: ix_payments_payment_intents_organization_id; Type: INDEX; Schema: payments; Owner: -
--

CREATE INDEX ix_payments_payment_intents_organization_id ON payments.payment_intents USING btree (organization_id);


--
-- Name: ix_payouts_professional; Type: INDEX; Schema: payments; Owner: -
--

CREATE INDEX ix_payouts_professional ON payments.payouts USING btree (professional_id, created_at);


--
-- Name: ix_refunds_org; Type: INDEX; Schema: payments; Owner: -
--

CREATE INDEX ix_refunds_org ON payments.refunds USING btree (organization_id, created_at);


--
-- Name: ix_outbox_unpublished; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_outbox_unpublished ON platform.outbox USING btree (seq) WHERE (published_at IS NULL);


--
-- Name: ix_timers_due; Type: INDEX; Schema: platform; Owner: -
--

CREATE INDEX ix_timers_due ON platform.timers USING btree (fire_at) WHERE ((fired_at IS NULL) AND (cancelled_at IS NULL));


--
-- Name: ix_policy_approvals_org_status; Type: INDEX; Schema: policy; Owner: -
--

CREATE INDEX ix_policy_approvals_org_status ON policy.approval_requests USING btree (organization_id, status);


--
-- Name: ix_policy_evaluations_subject; Type: INDEX; Schema: policy; Owner: -
--

CREATE INDEX ix_policy_evaluations_subject ON policy.policy_evaluations USING btree (organization_id, subject_id, action);


--
-- Name: ix_policy_exceptions_org_status; Type: INDEX; Schema: policy; Owner: -
--

CREATE INDEX ix_policy_exceptions_org_status ON policy.exception_requests USING btree (organization_id, status);


--
-- Name: ix_policy_profiles_org; Type: INDEX; Schema: policy; Owner: -
--

CREATE INDEX ix_policy_profiles_org ON policy.profiles USING btree (organization_id);


--
-- Name: ix_professional_credential_claims_professional_id; Type: INDEX; Schema: professional; Owner: -
--

CREATE INDEX ix_professional_credential_claims_professional_id ON professional.credential_claims USING btree (professional_id);


--
-- Name: ix_professional_offerings_professional_id; Type: INDEX; Schema: professional; Owner: -
--

CREATE INDEX ix_professional_offerings_professional_id ON professional.offerings USING btree (professional_id);


--
-- Name: ix_professional_saved_buyers_professional_id; Type: INDEX; Schema: professional; Owner: -
--

CREATE INDEX ix_professional_saved_buyers_professional_id ON professional.saved_buyers USING btree (professional_id);


--
-- Name: ix_proposals_org; Type: INDEX; Schema: proposal; Owner: -
--

CREATE INDEX ix_proposals_org ON proposal.proposals USING btree (organization_id, status);


--
-- Name: ix_proposals_professional; Type: INDEX; Schema: proposal; Owner: -
--

CREATE INDEX ix_proposals_professional ON proposal.proposals USING btree (professional_id, status);


--
-- Name: ix_requests_group; Type: INDEX; Schema: proposal; Owner: -
--

CREATE INDEX ix_requests_group ON proposal.requests USING btree (group_id);


--
-- Name: ix_requests_org; Type: INDEX; Schema: proposal; Owner: -
--

CREATE INDEX ix_requests_org ON proposal.requests USING btree (organization_id, created_at);


--
-- Name: ix_requests_professional; Type: INDEX; Schema: proposal; Owner: -
--

CREATE INDEX ix_requests_professional ON proposal.requests USING btree (professional_id, status, created_at);


--
-- Name: ix_review_reviews_professional_id; Type: INDEX; Schema: review; Owner: -
--

CREATE INDEX ix_review_reviews_professional_id ON review.reviews USING btree (professional_id);


--
-- Name: ix_professional_documents_document; Type: INDEX; Schema: search; Owner: -
--

CREATE INDEX ix_professional_documents_document ON search.professional_documents USING gin (document);


--
-- Name: ix_professional_documents_specializations; Type: INDEX; Schema: search; Owner: -
--

CREATE INDEX ix_professional_documents_specializations ON search.professional_documents USING gin (specializations);


--
-- Name: ix_trust_signals_professional_id; Type: INDEX; Schema: trust; Owner: -
--

CREATE INDEX ix_trust_signals_professional_id ON trust.signals USING btree (professional_id);


--
-- Name: ix_trust_tier_history_professional_id; Type: INDEX; Schema: trust; Owner: -
--

CREATE INDEX ix_trust_tier_history_professional_id ON trust.tier_history USING btree (professional_id);


--
-- Name: ix_appeals_status; Type: INDEX; Schema: verification; Owner: -
--

CREATE INDEX ix_appeals_status ON verification.appeals USING btree (status, created_at);


--
-- Name: ix_cases_queue; Type: INDEX; Schema: verification; Owner: -
--

CREATE INDEX ix_cases_queue ON verification.cases USING btree (status, created_at);


--
-- Name: ix_cases_subject; Type: INDEX; Schema: verification; Owner: -
--

CREATE INDEX ix_cases_subject ON verification.cases USING btree (subject_type, subject_id);


--
-- Name: ix_verification_evidence_checks_case_id; Type: INDEX; Schema: verification; Owner: -
--

CREATE INDEX ix_verification_evidence_checks_case_id ON verification.evidence_checks USING btree (case_id);


--
-- Name: ix_verification_evidence_items_case_id; Type: INDEX; Schema: verification; Owner: -
--

CREATE INDEX ix_verification_evidence_items_case_id ON verification.evidence_items USING btree (case_id);


--
-- Name: inference_logs trg_inference_logs_append_only; Type: TRIGGER; Schema: ai; Owner: -
--

CREATE TRIGGER trg_inference_logs_append_only BEFORE DELETE OR UPDATE ON ai.inference_logs FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();


--
-- Name: prompt_versions trg_prompt_immutable; Type: TRIGGER; Schema: ai; Owner: -
--

CREATE TRIGGER trg_prompt_immutable BEFORE DELETE OR UPDATE ON ai.prompt_versions FOR EACH ROW EXECUTE FUNCTION ai.guard_prompt();


--
-- Name: audit_records trg_audit_records_append_only; Type: TRIGGER; Schema: audit; Owner: -
--

CREATE TRIGGER trg_audit_records_append_only BEFORE DELETE OR UPDATE ON audit.audit_records FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();


--
-- Name: change_orders trg_change_orders_append_only; Type: TRIGGER; Schema: contract; Owner: -
--

CREATE TRIGGER trg_change_orders_append_only BEFORE DELETE OR UPDATE ON contract.change_orders FOR EACH ROW EXECUTE FUNCTION contract.guard_change_order_history();


--
-- Name: contract_revisions trg_contract_revisions_append_only; Type: TRIGGER; Schema: contract; Owner: -
--

CREATE TRIGGER trg_contract_revisions_append_only BEFORE DELETE OR UPDATE ON contract.contract_revisions FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();


--
-- Name: signatures trg_signatures_append_only; Type: TRIGGER; Schema: contract; Owner: -
--

CREATE TRIGGER trg_signatures_append_only BEFORE DELETE OR UPDATE ON contract.signatures FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();


--
-- Name: appeals trg_appeal_immutable; Type: TRIGGER; Schema: dispute; Owner: -
--

CREATE TRIGGER trg_appeal_immutable BEFORE DELETE OR UPDATE ON dispute.appeals FOR EACH ROW EXECUTE FUNCTION dispute.guard_appeal();


--
-- Name: cases trg_decision_immutable; Type: TRIGGER; Schema: dispute; Owner: -
--

CREATE TRIGGER trg_decision_immutable BEFORE UPDATE ON dispute.cases FOR EACH ROW EXECUTE FUNCTION dispute.guard_decision();


--
-- Name: evidence_items trg_evidence_items_append_only; Type: TRIGGER; Schema: dispute; Owner: -
--

CREATE TRIGGER trg_evidence_items_append_only BEFORE DELETE OR UPDATE ON dispute.evidence_items FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();


--
-- Name: ledger_entries trg_ledger_entries_append_only; Type: TRIGGER; Schema: escrow; Owner: -
--

CREATE TRIGGER trg_ledger_entries_append_only BEFORE DELETE OR UPDATE ON escrow.ledger_entries FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();


--
-- Name: attachments trg_attachments_append_only; Type: TRIGGER; Schema: messaging; Owner: -
--

CREATE TRIGGER trg_attachments_append_only BEFORE DELETE OR UPDATE ON messaging.attachments FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();


--
-- Name: messages trg_messages_append_only; Type: TRIGGER; Schema: messaging; Owner: -
--

CREATE TRIGGER trg_messages_append_only BEFORE DELETE OR UPDATE ON messaging.messages FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation_except_name_erasure('sender_name');


--
-- Name: delivery_attempts prevent_mutation; Type: TRIGGER; Schema: notification; Owner: -
--

CREATE TRIGGER prevent_mutation BEFORE DELETE OR UPDATE ON notification.delivery_attempts FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();


--
-- Name: approval_votes trg_approval_votes_append_only; Type: TRIGGER; Schema: policy; Owner: -
--

CREATE TRIGGER trg_approval_votes_append_only BEFORE DELETE OR UPDATE ON policy.approval_votes FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();


--
-- Name: policy_evaluations trg_policy_evaluations_append_only; Type: TRIGGER; Schema: policy; Owner: -
--

CREATE TRIGGER trg_policy_evaluations_append_only BEFORE DELETE OR UPDATE ON policy.policy_evaluations FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();


--
-- Name: versions trg_policy_versions_immutable; Type: TRIGGER; Schema: policy; Owner: -
--

CREATE TRIGGER trg_policy_versions_immutable BEFORE DELETE OR UPDATE ON policy.versions FOR EACH ROW EXECUTE FUNCTION policy.guard_active_version();


--
-- Name: reviews trg_reviews_append_only; Type: TRIGGER; Schema: review; Owner: -
--

CREATE TRIGGER trg_reviews_append_only BEFORE DELETE OR UPDATE ON review.reviews FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation_except_name_erasure('reviewer_name');


--
-- Name: evidence_items trg_evidence_items_append_only; Type: TRIGGER; Schema: verification; Owner: -
--

CREATE TRIGGER trg_evidence_items_append_only BEFORE DELETE OR UPDATE ON verification.evidence_items FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();


--
-- Name: provider_events trg_provider_events_append_only; Type: TRIGGER; Schema: verification; Owner: -
--

CREATE TRIGGER trg_provider_events_append_only BEFORE DELETE OR UPDATE ON verification.provider_events FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation();


--
-- Name: billing_contacts fk_billing_contacts_organization_id_organizations; Type: FK CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.billing_contacts
    ADD CONSTRAINT fk_billing_contacts_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES buyer.organizations(id);


--
-- Name: business_units fk_business_units_organization_id_organizations; Type: FK CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.business_units
    ADD CONSTRAINT fk_business_units_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES buyer.organizations(id);


--
-- Name: business_units fk_business_units_parent_id_business_units; Type: FK CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.business_units
    ADD CONSTRAINT fk_business_units_parent_id_business_units FOREIGN KEY (parent_id) REFERENCES buyer.business_units(id);


--
-- Name: cost_centers fk_cost_centers_business_unit_id_business_units; Type: FK CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.cost_centers
    ADD CONSTRAINT fk_cost_centers_business_unit_id_business_units FOREIGN KEY (business_unit_id) REFERENCES buyer.business_units(id);


--
-- Name: cost_centers fk_cost_centers_organization_id_organizations; Type: FK CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.cost_centers
    ADD CONSTRAINT fk_cost_centers_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES buyer.organizations(id);


--
-- Name: invitations fk_invitations_organization_id_organizations; Type: FK CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.invitations
    ADD CONSTRAINT fk_invitations_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES buyer.organizations(id);


--
-- Name: members fk_members_organization_id_organizations; Type: FK CONSTRAINT; Schema: buyer; Owner: -
--

ALTER TABLE ONLY buyer.members
    ADD CONSTRAINT fk_members_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES buyer.organizations(id);


--
-- Name: change_orders fk_change_orders_contract_id_contracts; Type: FK CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.change_orders
    ADD CONSTRAINT fk_change_orders_contract_id_contracts FOREIGN KEY (contract_id) REFERENCES contract.contracts(id);


--
-- Name: contract_revisions fk_contract_revisions_change_order_id_change_orders; Type: FK CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.contract_revisions
    ADD CONSTRAINT fk_contract_revisions_change_order_id_change_orders FOREIGN KEY (change_order_id) REFERENCES contract.change_orders(id);


--
-- Name: contract_revisions fk_contract_revisions_contract_id_contracts; Type: FK CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.contract_revisions
    ADD CONSTRAINT fk_contract_revisions_contract_id_contracts FOREIGN KEY (contract_id) REFERENCES contract.contracts(id);


--
-- Name: contracts fk_contracts_pending_change_order_id_change_orders; Type: FK CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.contracts
    ADD CONSTRAINT fk_contracts_pending_change_order_id_change_orders FOREIGN KEY (pending_change_order_id) REFERENCES contract.change_orders(id);


--
-- Name: milestones fk_milestones_contract_id_contracts; Type: FK CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.milestones
    ADD CONSTRAINT fk_milestones_contract_id_contracts FOREIGN KEY (contract_id) REFERENCES contract.contracts(id);


--
-- Name: signatures fk_signatures_contract_id_contracts; Type: FK CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.signatures
    ADD CONSTRAINT fk_signatures_contract_id_contracts FOREIGN KEY (contract_id) REFERENCES contract.contracts(id);


--
-- Name: submissions fk_submissions_milestone_id_milestones; Type: FK CONSTRAINT; Schema: contract; Owner: -
--

ALTER TABLE ONLY contract.submissions
    ADD CONSTRAINT fk_submissions_milestone_id_milestones FOREIGN KEY (milestone_id) REFERENCES contract.milestones(id);


--
-- Name: appeals fk_appeals_case_id_cases; Type: FK CONSTRAINT; Schema: dispute; Owner: -
--

ALTER TABLE ONLY dispute.appeals
    ADD CONSTRAINT fk_appeals_case_id_cases FOREIGN KEY (case_id) REFERENCES dispute.cases(id);


--
-- Name: evidence_items fk_evidence_items_case_id_cases; Type: FK CONSTRAINT; Schema: dispute; Owner: -
--

ALTER TABLE ONLY dispute.evidence_items
    ADD CONSTRAINT fk_evidence_items_case_id_cases FOREIGN KEY (case_id) REFERENCES dispute.cases(id);


--
-- Name: resolution_proposals fk_resolution_proposals_case_id_cases; Type: FK CONSTRAINT; Schema: dispute; Owner: -
--

ALTER TABLE ONLY dispute.resolution_proposals
    ADD CONSTRAINT fk_resolution_proposals_case_id_cases FOREIGN KEY (case_id) REFERENCES dispute.cases(id);


--
-- Name: timeline fk_timeline_case_id_cases; Type: FK CONSTRAINT; Schema: dispute; Owner: -
--

ALTER TABLE ONLY dispute.timeline
    ADD CONSTRAINT fk_timeline_case_id_cases FOREIGN KEY (case_id) REFERENCES dispute.cases(id);


--
-- Name: allocations fk_allocations_account_id_accounts; Type: FK CONSTRAINT; Schema: escrow; Owner: -
--

ALTER TABLE ONLY escrow.allocations
    ADD CONSTRAINT fk_allocations_account_id_accounts FOREIGN KEY (account_id) REFERENCES escrow.accounts(id);


--
-- Name: fundings fk_fundings_account_id_accounts; Type: FK CONSTRAINT; Schema: escrow; Owner: -
--

ALTER TABLE ONLY escrow.fundings
    ADD CONSTRAINT fk_fundings_account_id_accounts FOREIGN KEY (account_id) REFERENCES escrow.accounts(id);


--
-- Name: ledger_entries fk_ledger_entries_account_id_accounts; Type: FK CONSTRAINT; Schema: escrow; Owner: -
--

ALTER TABLE ONLY escrow.ledger_entries
    ADD CONSTRAINT fk_ledger_entries_account_id_accounts FOREIGN KEY (account_id) REFERENCES escrow.accounts(id);


--
-- Name: releases fk_releases_account_id_accounts; Type: FK CONSTRAINT; Schema: escrow; Owner: -
--

ALTER TABLE ONLY escrow.releases
    ADD CONSTRAINT fk_releases_account_id_accounts FOREIGN KEY (account_id) REFERENCES escrow.accounts(id);


--
-- Name: invitations fk_invitations_firm_id_firms; Type: FK CONSTRAINT; Schema: firm; Owner: -
--

ALTER TABLE ONLY firm.invitations
    ADD CONSTRAINT fk_invitations_firm_id_firms FOREIGN KEY (firm_id) REFERENCES firm.firms(id);


--
-- Name: members fk_members_firm_id_firms; Type: FK CONSTRAINT; Schema: firm; Owner: -
--

ALTER TABLE ONLY firm.members
    ADD CONSTRAINT fk_members_firm_id_firms FOREIGN KEY (firm_id) REFERENCES firm.firms(id);


--
-- Name: consent_records fk_consent_records_identity_id_identities; Type: FK CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.consent_records
    ADD CONSTRAINT fk_consent_records_identity_id_identities FOREIGN KEY (identity_id) REFERENCES identity.identities(id);


--
-- Name: data_requests fk_data_requests_identity_id_identities; Type: FK CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.data_requests
    ADD CONSTRAINT fk_data_requests_identity_id_identities FOREIGN KEY (identity_id) REFERENCES identity.identities(id);


--
-- Name: identity_links fk_identity_links_identity_id_identities; Type: FK CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.identity_links
    ADD CONSTRAINT fk_identity_links_identity_id_identities FOREIGN KEY (identity_id) REFERENCES identity.identities(id);


--
-- Name: sessions fk_sessions_identity_id_identities; Type: FK CONSTRAINT; Schema: identity; Owner: -
--

ALTER TABLE ONLY identity.sessions
    ADD CONSTRAINT fk_sessions_identity_id_identities FOREIGN KEY (identity_id) REFERENCES identity.identities(id);


--
-- Name: collection_items fk_collection_items_collection_id_collections; Type: FK CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.collection_items
    ADD CONSTRAINT fk_collection_items_collection_id_collections FOREIGN KEY (collection_id) REFERENCES marketplace.collections(id) ON DELETE CASCADE;


--
-- Name: taxonomy_nodes fk_taxonomy_nodes_parent_id_taxonomy_nodes; Type: FK CONSTRAINT; Schema: marketplace; Owner: -
--

ALTER TABLE ONLY marketplace.taxonomy_nodes
    ADD CONSTRAINT fk_taxonomy_nodes_parent_id_taxonomy_nodes FOREIGN KEY (parent_id) REFERENCES marketplace.taxonomy_nodes(id);


--
-- Name: attachments fk_attachments_thread_id_threads; Type: FK CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.attachments
    ADD CONSTRAINT fk_attachments_thread_id_threads FOREIGN KEY (thread_id) REFERENCES messaging.threads(id);


--
-- Name: messages fk_messages_thread_id_threads; Type: FK CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.messages
    ADD CONSTRAINT fk_messages_thread_id_threads FOREIGN KEY (thread_id) REFERENCES messaging.threads(id);


--
-- Name: read_positions fk_read_positions_thread_id_threads; Type: FK CONSTRAINT; Schema: messaging; Owner: -
--

ALTER TABLE ONLY messaging.read_positions
    ADD CONSTRAINT fk_read_positions_thread_id_threads FOREIGN KEY (thread_id) REFERENCES messaging.threads(id);


--
-- Name: delivery_attempts fk_delivery_attempts_delivery_id_webhook_deliveries; Type: FK CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.delivery_attempts
    ADD CONSTRAINT fk_delivery_attempts_delivery_id_webhook_deliveries FOREIGN KEY (delivery_id) REFERENCES notification.webhook_deliveries(id);


--
-- Name: webhook_deliveries fk_webhook_deliveries_endpoint_id_webhook_endpoints; Type: FK CONSTRAINT; Schema: notification; Owner: -
--

ALTER TABLE ONLY notification.webhook_deliveries
    ADD CONSTRAINT fk_webhook_deliveries_endpoint_id_webhook_endpoints FOREIGN KEY (endpoint_id) REFERENCES notification.webhook_endpoints(id);


--
-- Name: approval_votes fk_approval_votes_request_id_approval_requests; Type: FK CONSTRAINT; Schema: policy; Owner: -
--

ALTER TABLE ONLY policy.approval_votes
    ADD CONSTRAINT fk_approval_votes_request_id_approval_requests FOREIGN KEY (request_id) REFERENCES policy.approval_requests(id);


--
-- Name: versions fk_versions_profile_id_profiles; Type: FK CONSTRAINT; Schema: policy; Owner: -
--

ALTER TABLE ONLY policy.versions
    ADD CONSTRAINT fk_versions_profile_id_profiles FOREIGN KEY (profile_id) REFERENCES policy.profiles(id);


--
-- Name: credential_claims fk_credential_claims_professional_id_professionals; Type: FK CONSTRAINT; Schema: professional; Owner: -
--

ALTER TABLE ONLY professional.credential_claims
    ADD CONSTRAINT fk_credential_claims_professional_id_professionals FOREIGN KEY (professional_id) REFERENCES professional.professionals(id);


--
-- Name: offerings fk_offerings_professional_id_professionals; Type: FK CONSTRAINT; Schema: professional; Owner: -
--

ALTER TABLE ONLY professional.offerings
    ADD CONSTRAINT fk_offerings_professional_id_professionals FOREIGN KEY (professional_id) REFERENCES professional.professionals(id);


--
-- Name: saved_buyers fk_saved_buyers_professional_id_professionals; Type: FK CONSTRAINT; Schema: professional; Owner: -
--

ALTER TABLE ONLY professional.saved_buyers
    ADD CONSTRAINT fk_saved_buyers_professional_id_professionals FOREIGN KEY (professional_id) REFERENCES professional.professionals(id);


--
-- Name: proposals fk_proposals_request_id_requests; Type: FK CONSTRAINT; Schema: proposal; Owner: -
--

ALTER TABLE ONLY proposal.proposals
    ADD CONSTRAINT fk_proposals_request_id_requests FOREIGN KEY (request_id) REFERENCES proposal.requests(id);


--
-- Name: appeals fk_appeals_case_id_cases; Type: FK CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.appeals
    ADD CONSTRAINT fk_appeals_case_id_cases FOREIGN KEY (case_id) REFERENCES verification.cases(id);


--
-- Name: evidence_checks fk_evidence_checks_case_id_cases; Type: FK CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.evidence_checks
    ADD CONSTRAINT fk_evidence_checks_case_id_cases FOREIGN KEY (case_id) REFERENCES verification.cases(id);


--
-- Name: evidence_checks fk_evidence_checks_evidence_id_evidence_items; Type: FK CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.evidence_checks
    ADD CONSTRAINT fk_evidence_checks_evidence_id_evidence_items FOREIGN KEY (evidence_id) REFERENCES verification.evidence_items(id);


--
-- Name: evidence_items fk_evidence_items_case_id_cases; Type: FK CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.evidence_items
    ADD CONSTRAINT fk_evidence_items_case_id_cases FOREIGN KEY (case_id) REFERENCES verification.cases(id);


--
-- Name: provider_sessions fk_provider_sessions_case_id_cases; Type: FK CONSTRAINT; Schema: verification; Owner: -
--

ALTER TABLE ONLY verification.provider_sessions
    ADD CONSTRAINT fk_provider_sessions_case_id_cases FOREIGN KEY (case_id) REFERENCES verification.cases(id);


--
-- PostgreSQL database dump complete
--

\unrestrict NhABbKmlu7wQMwYIUcrwzNQUArmUvOyOKWmJE0nMF2kKwtvEwqp4DWob1JNHb9n

