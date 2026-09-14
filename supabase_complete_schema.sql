-- ============================================================
-- SUPABASE DATABASE EXPORT
-- ============================================================
-- Generated: 2026-09-14 12:51:52.242382
-- Schema: public
-- Generated using Python + psycopg
-- ============================================================

BEGIN;


-- ============================================================
-- EXTENSIONS
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "supabase_vault";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ============================================================
-- ENUM TYPES
-- ============================================================



-- ============================================================
-- SEQUENCES
-- ============================================================

CREATE SEQUENCE IF NOT EXISTS "public"."whatsapp_auth_files_id_seq";
CREATE SEQUENCE IF NOT EXISTS "public"."whatsapp_auth_id_seq";
CREATE SEQUENCE IF NOT EXISTS "public"."whatsapp_sessions_id_seq";


-- ============================================================
-- TABLES
-- ============================================================

CREATE TABLE "public"."academic_terms" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "term_name" character varying NOT NULL,
    "academic_year" integer NOT NULL,
    "start_date" date,
    "end_date" date,
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."advance_payments" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "advance_id" uuid NOT NULL,
    "employee_id" uuid NOT NULL,
    "amount" numeric NOT NULL,
    "payment_month" character varying NOT NULL,
    "payment_date" date NOT NULL,
    "is_repayment" boolean DEFAULT true,
    "notes" text,
    "created_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."agent_applications" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "full_name" character varying NOT NULL,
    "phone" character varying NOT NULL,
    "email" character varying,
    "region" character varying NOT NULL,
    "identification_document" text,
    "device_fingerprint" character varying,
    "status" character varying DEFAULT 'pending'::character varying,
    "rejection_reason" text,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."agent_submissions" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "task_id" uuid,
    "agent_id" uuid,
    "gps_latitude" numeric,
    "gps_longitude" numeric,
    "gps_accuracy" numeric,
    "ip_address" character varying,
    "device_fingerprint" character varying,
    "proof_url" text,
    "notes" text,
    "location_verified" boolean DEFAULT false,
    "distance_from_ip" numeric,
    "vpn_detected" boolean DEFAULT false,
    "status" character varying DEFAULT 'pending'::character varying,
    "rejection_reason" text,
    "approved_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."agent_tasks" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "title" character varying NOT NULL,
    "description" text,
    "region" character varying NOT NULL,
    "payment_amount" numeric NOT NULL,
    "deadline" date,
    "status" character varying DEFAULT 'active'::character varying,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."agents" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "application_id" uuid,
    "full_name" character varying NOT NULL,
    "phone" character varying NOT NULL,
    "email" character varying,
    "region" character varying NOT NULL,
    "status" character varying DEFAULT 'active'::character varying,
    "total_earnings" numeric DEFAULT 0,
    "tasks_completed" integer DEFAULT 0,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."asset_transactions" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "account_id" uuid NOT NULL,
    "institute_id" uuid NOT NULL,
    "amount" numeric NOT NULL,
    "transaction_type" character varying NOT NULL,
    "description" text,
    "notes" text,
    "transaction_date" date NOT NULL,
    "reference_number" character varying,
    "created_at" timestamp without time zone DEFAULT now(),
    "updated_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."attendance" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "student_id" uuid,
    "student_name" character varying NOT NULL,
    "student_number" character varying NOT NULL,
    "class_name" character varying,
    "scan_time" timestamp with time zone NOT NULL,
    "scan_date" date NOT NULL,
    "created_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."budget_headers" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "name" text NOT NULL,
    "fiscal_year" integer NOT NULL,
    "period_type" text NOT NULL,
    "status" text DEFAULT 'draft'::text,
    "start_date" date,
    "end_date" date,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "description" text
);

CREATE TABLE "public"."budget_lines" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "budget_header_id" uuid NOT NULL,
    "account_id" uuid NOT NULL,
    "period_index" integer NOT NULL,
    "budgeted_amount" numeric DEFAULT 0.00
);

CREATE TABLE "public"."budgets" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "account_id" uuid NOT NULL,
    "fiscal_year" integer NOT NULL,
    "budgeted_amount" numeric DEFAULT 0.00,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."cdc_report_settings" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "grading_scale" jsonb DEFAULT '[{"max": 100, "min": 75, "grade": "A", "label": "Exceptional", "range": "100 - 75"}, {"max": 74, "min": 60, "grade": "B", "label": "Outstanding", "range": "75 - 60"}, {"max": 59, "min": 50, "grade": "C", "label": "Satisfactory", "range": "60 - 50"}, {"max": 49, "min": 35, "grade": "D", "label": "Basic", "range": "50 - 35"}, {"max": 34, "min": 0, "grade": "E", "label": "Insufficient", "range": "35 - 0"}]'::jsonb NOT NULL,
    "result_definitions" jsonb DEFAULT '[{"id": "result_1", "text": "The learner sits for minimum 8 subjects with grade D and above in all subjects", "label": "Result 1"}, {"id": "result_2", "text": "The learner sits for minimum 8 subjects but with grade E in not more than 2 subjects", "label": "Result 2"}, {"id": "result_3", "text": "The learner scores only grade E in the subjects taken", "label": "Result 3"}]'::jsonb NOT NULL,
    "key_terms" jsonb DEFAULT '[{"code": "A1", "label": "Average Chapter Assessment (20% weight)"}, {"code": "80%", "label": "End of Term Assessment (80% weight)"}, {"code": "TR", "label": "Teacher''s Initials"}]'::jsonb NOT NULL,
    "weighted_columns" jsonb DEFAULT '[{"key": "20%", "label": "20%"}, {"key": "80%", "label": "80%"}, {"key": "100%", "label": "100%"}]'::jsonb NOT NULL,
    "identifier_rules" jsonb DEFAULT '[{"id": "ident_1", "max": 39, "min": 0, "label": "Identifier 1", "description": "Below Average"}, {"id": "ident_2", "max": 69, "min": 40, "label": "Identifier 2", "description": "Average"}, {"id": "ident_3", "max": 100, "min": 70, "label": "Identifier 3", "description": "Above Average"}]'::jsonb NOT NULL,
    "achievement_levels" jsonb DEFAULT '[{"max": 100, "min": 80, "color": "#10b981", "level": "Excellent"}, {"max": 79, "min": 70, "color": "#3b82f6", "level": "Very Good"}, {"max": 69, "min": 60, "color": "#f59e0b", "level": "Good"}, {"max": 59, "min": 40, "color": "#f97316", "level": "Average"}, {"max": 39, "min": 0, "color": "#ef4444", "level": "Needs Improvement"}]'::jsonb NOT NULL,
    "report_title" character varying DEFAULT 'COMPETENCY BASED ASSESSMENT REPORT'::character varying NOT NULL,
    "show_photo" boolean DEFAULT true,
    "show_logo" boolean DEFAULT true,
    "show_aggregates" boolean DEFAULT true,
    "footer_fields" jsonb DEFAULT '[{"key": "term_ended_on", "label": "Term Ended On"}, {"key": "next_term_begins", "label": "Next Term Begins"}, {"key": "fees_balance", "label": "Fees Balance"}, {"key": "fees_next_term", "label": "Fees Next Term"}, {"key": "other_requirement", "label": "Other Requirement"}]'::jsonb NOT NULL,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "updated_by" uuid
);

CREATE TABLE "public"."chart_of_accounts" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "account_code" character varying NOT NULL,
    "account_name" character varying NOT NULL,
    "account_type" character varying NOT NULL,
    "description" text,
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."class_enrollments" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "student_id" uuid,
    "class_id" uuid,
    "enrolled_at" timestamp with time zone DEFAULT now(),
    "academic_year" integer,
    "updated_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."class_requirements" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "item_id" uuid NOT NULL,
    "class_id" uuid,
    "apply_to_all" boolean DEFAULT false,
    "quantity_required" numeric NOT NULL,
    "term_id" uuid,
    "academic_year" integer,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."class_sections" (
    "class_id" uuid NOT NULL,
    "section_id" uuid NOT NULL,
    "created_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."class_subjects" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "class_id" uuid,
    "subject_id" uuid,
    "marks" numeric DEFAULT 100 NOT NULL,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "teacher_id" uuid
);

CREATE TABLE "public"."classes" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "name" character varying NOT NULL,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."discounts" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "student_id" uuid,
    "student_name" character varying,
    "invoice_id" uuid,
    "discount_type" character varying NOT NULL,
    "discount_value" numeric NOT NULL,
    "discount_amount" numeric,
    "apply_to" character varying NOT NULL,
    "target_id" uuid,
    "reason" text,
    "valid_from" date,
    "valid_until" date,
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."division_rules" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "division" text NOT NULL,
    "min_aggregate" integer,
    "max_aggregate" integer,
    "requires" text[],
    "min_grade" text,
    "fail_if_any_f9" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."employee_advances" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "employee_id" uuid NOT NULL,
    "advance_amount" numeric DEFAULT 0 NOT NULL,
    "repaid_amount" numeric DEFAULT 0 NOT NULL,
    "remaining_amount" numeric DEFAULT 0 NOT NULL,
    "advance_month" character varying NOT NULL,
    "repayment_start_month" character varying,
    "repayment_end_month" character varying,
    "repayment_months" integer DEFAULT 1,
    "monthly_deduction" numeric DEFAULT 0,
    "purpose" text,
    "status" character varying DEFAULT 'active'::character varying,
    "approved_by" uuid,
    "approved_at" timestamp without time zone,
    "notes" text,
    "created_at" timestamp without time zone DEFAULT now(),
    "updated_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."employee_permissions" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "employee_id" uuid NOT NULL,
    "institute_id" uuid NOT NULL,
    "permissions" jsonb DEFAULT '{}'::jsonb,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."employees" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "employee_id" character varying NOT NULL,
    "name" character varying NOT NULL,
    "gender" character varying,
    "date_of_birth" date,
    "date_of_joining" date,
    "father_husband_name" character varying,
    "national_id" character varying,
    "education" character varying,
    "home_address" text,
    "experience" character varying,
    "email" character varying,
    "phone" character varying,
    "monthly_salary" numeric DEFAULT 0,
    "role" character varying,
    "photo_url" text,
    "photo_public_id" text,
    "status" character varying DEFAULT 'active'::character varying,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "password_hash" text,
    "permissions_override" jsonb
);

CREATE TABLE "public"."exam_fail_criteria" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "overall_percentage" numeric DEFAULT 30,
    "subject_percentage" numeric DEFAULT 15,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."exam_grading" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "grade_name" character varying NOT NULL,
    "min_percentage" numeric NOT NULL,
    "max_percentage" numeric NOT NULL,
    "status" character varying DEFAULT 'Pass'::character varying,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "class_teacher_comment" text,
    "head_teacher_comment" text,
    "requirements" text
);

CREATE TABLE "public"."exam_grading_requirements" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "next_term_date" date,
    "next_term_text" text DEFAULT 'To be announced'::text,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."exam_marks" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "exam_id" uuid,
    "class_id" uuid,
    "student_id" uuid,
    "subject_id" uuid,
    "obtained_marks" numeric NOT NULL,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "marksheet_id" uuid,
    "exam_total_marks" numeric,
    "academic_year" text,
    "term" text
);

CREATE TABLE "public"."exam_marks_history" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "exam_id" uuid,
    "class_id" uuid,
    "student_id" uuid,
    "subject_id" uuid,
    "obtained_marks" numeric NOT NULL,
    "record_date" date NOT NULL,
    "created_at" timestamp with time zone DEFAULT now(),
    "marksheet_id" uuid,
    "exam_total_marks" numeric
);

CREATE TABLE "public"."exam_marksheets" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "exam_id" uuid NOT NULL,
    "class_id" uuid NOT NULL,
    "academic_year" integer NOT NULL,
    "marksheet_number" character varying,
    "generated_at" timestamp with time zone DEFAULT now(),
    "created_at" timestamp with time zone DEFAULT now(),
    "term" character varying
);

CREATE TABLE "public"."exams" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "exam_name" character varying NOT NULL,
    "start_date" date,
    "end_date" date,
    "is_published" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "total_marks" numeric DEFAULT 0,
    "exam_date" date NOT NULL,
    "term" character varying DEFAULT 'Term 1'::character varying NOT NULL,
    "academic_year" character varying DEFAULT '2026'::character varying NOT NULL,
    "class_id" uuid
);

CREATE TABLE "public"."expense_transactions" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "account_id" uuid,
    "amount" numeric NOT NULL,
    "transaction_date" date NOT NULL,
    "payment_method" character varying,
    "reference_number" character varying,
    "description" text,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "employee_id" uuid,
    "vendor" text
);

CREATE TABLE "public"."fee_names" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "fee_name" character varying NOT NULL,
    "standard_amount" numeric NOT NULL,
    "is_optional" boolean DEFAULT false,
    "description" text,
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."fee_particulars" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "student_id" uuid,
    "class_id" uuid,
    "apply_to" character varying NOT NULL,
    "fee_items" jsonb NOT NULL,
    "total_amount" numeric NOT NULL,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."income_transactions" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "account_id" uuid,
    "amount" numeric NOT NULL,
    "transaction_date" date NOT NULL,
    "payment_method" character varying,
    "reference_number" character varying,
    "description" text,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."institutes" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "user_id" uuid,
    "institute_code" character varying NOT NULL,
    "institute_name" character varying,
    "logo_url" text,
    "logo_public_id" text,
    "phone_number" character varying,
    "email" character varying,
    "website" character varying,
    "address" text,
    "target_line" text,
    "country" character varying,
    "balance" numeric DEFAULT 0,
    "total_spent" numeric DEFAULT 0,
    "last_balance_update" timestamp without time zone DEFAULT now(),
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "status" text DEFAULT 'active'::text NOT NULL
);

CREATE TABLE "public"."inventory" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "item_id" uuid,
    "quantity" integer NOT NULL,
    "transaction_type" character varying NOT NULL,
    "reason" text,
    "transaction_date" date NOT NULL,
    "created_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."inventory_transactions" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "item_id" uuid NOT NULL,
    "quantity" numeric NOT NULL,
    "transaction_type" character varying NOT NULL,
    "source" character varying,
    "reference_id" uuid,
    "notes" text,
    "used_by" uuid,
    "created_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."invoices" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "student_id" uuid,
    "particulars_id" uuid,
    "invoice_number" character varying NOT NULL,
    "total_amount" numeric NOT NULL,
    "paid_amount" numeric DEFAULT 0,
    "balance" numeric NOT NULL,
    "status" character varying DEFAULT 'pending'::character varying,
    "due_date" date,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "discount_applied" numeric DEFAULT 0
);

CREATE TABLE "public"."liability_transactions" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "account_id" uuid NOT NULL,
    "institute_id" uuid NOT NULL,
    "amount" numeric NOT NULL,
    "transaction_type" character varying NOT NULL,
    "description" text,
    "notes" text,
    "transaction_date" date NOT NULL,
    "reference_number" character varying,
    "created_at" timestamp without time zone DEFAULT now(),
    "updated_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."manual_payment_requests" (
    "id" uuid NOT NULL,
    "institute_id" uuid,
    "amount" numeric,
    "reference" character varying,
    "status" character varying DEFAULT 'pending'::character varying,
    "admin_notes" text,
    "created_at" timestamp without time zone DEFAULT now(),
    "updated_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."message_logs" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "sender_id" character varying,
    "message" text,
    "recipient_count" integer,
    "status" character varying DEFAULT 'sent'::character varying,
    "created_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."next_term_settings" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "next_term_date" date,
    "next_term_text" text,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."organization_billing" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "start_date" date NOT NULL,
    "expiry_date" date NOT NULL,
    "status" character varying DEFAULT 'active'::character varying,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."payment_transactions" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "order_tracking_id" character varying,
    "merchant_reference" character varying,
    "amount" numeric NOT NULL,
    "months" integer NOT NULL,
    "status" character varying DEFAULT 'pending'::character varying,
    "payment_method" character varying,
    "payment_status" character varying,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."payments" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "invoice_id" uuid,
    "student_id" uuid,
    "amount" numeric NOT NULL,
    "payment_method" character varying,
    "receipt_number" character varying,
    "payment_date" date,
    "notes" text,
    "created_at" timestamp with time zone DEFAULT now(),
    "fee_month" character varying,
    "whatsapp_status" character varying DEFAULT 'pending'::character varying,
    "whatsapp_sent_at" timestamp without time zone,
    "whatsapp_sent_count" integer DEFAULT 0,
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."report_templates" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "name" text NOT NULL,
    "template_data" jsonb DEFAULT '{}'::jsonb NOT NULL,
    "html_template" text,
    "css_style" text,
    "is_default" boolean DEFAULT false,
    "created_at" timestamp without time zone DEFAULT now(),
    "updated_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."requirement_items" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "name" character varying NOT NULL,
    "unit" character varying NOT NULL,
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."role_permissions" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "role" text NOT NULL,
    "menu_overrides" jsonb DEFAULT '{}'::jsonb NOT NULL,
    "route_overrides" jsonb DEFAULT '{}'::jsonb NOT NULL,
    "display_name" text,
    "description" text,
    "is_active" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."salary_payments" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "employee_id" uuid,
    "amount" numeric NOT NULL,
    "payment_month" character varying NOT NULL,
    "payment_date" date NOT NULL,
    "payment_method" character varying,
    "receipt_number" character varying,
    "notes" text,
    "status" character varying DEFAULT 'paid'::character varying,
    "created_at" timestamp with time zone DEFAULT now(),
    "gross_salary" numeric DEFAULT 0,
    "deductions" numeric DEFAULT 0,
    "bonuses" numeric DEFAULT 0,
    "advance_deduction" numeric DEFAULT 0
);

CREATE TABLE "public"."schoolpay_accounts" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "account_name" character varying NOT NULL,
    "school_code" character varying NOT NULL,
    "api_password" character varying NOT NULL,
    "environment" character varying DEFAULT 'sandbox'::character varying,
    "is_active" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."schoolpay_settings" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "school_code" character varying NOT NULL,
    "api_password" character varying NOT NULL,
    "api_username" character varying,
    "environment" character varying DEFAULT 'sandbox'::character varying,
    "is_active" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."sections" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "name" character varying NOT NULL,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."sms_credits" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "credits_available" integer DEFAULT 0,
    "total_credits_purchased" integer DEFAULT 0,
    "total_credits_used" integer DEFAULT 0,
    "last_updated" timestamp without time zone DEFAULT now(),
    "created_at" timestamp without time zone DEFAULT now(),
    "updated_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."sms_log" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "student_id" uuid,
    "phone_number" character varying,
    "message" text,
    "message_length" integer,
    "segments" integer,
    "cost" numeric,
    "status" character varying,
    "error_message" text,
    "sent_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."sms_payment_transactions" (
    "id" uuid NOT NULL,
    "institute_id" uuid,
    "order_tracking_id" character varying,
    "merchant_reference" character varying,
    "amount" numeric,
    "credits_purchased" integer,
    "package_name" character varying,
    "status" character varying,
    "payment_status" text,
    "payment_method" character varying,
    "created_at" timestamp without time zone,
    "updated_at" timestamp without time zone
);

CREATE TABLE "public"."sms_sent_log" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "student_id" uuid,
    "phone_number" character varying,
    "message" text,
    "segments" integer,
    "cost_credits" integer,
    "status" character varying,
    "error_message" text,
    "sent_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."sms_settings" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "api_username" character varying,
    "api_key" character varying,
    "sender_id" character varying DEFAULT 'SCHOOL'::character varying,
    "enabled" boolean DEFAULT false,
    "send_on_payment" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "cost_per_sms" integer DEFAULT 35
);

CREATE TABLE "public"."staff_attendance" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "employee_id" uuid,
    "employee_name" character varying NOT NULL,
    "employee_number" character varying NOT NULL,
    "role" character varying,
    "photo_url" text,
    "check_in_time" timestamp with time zone NOT NULL,
    "attendance_date" date NOT NULL,
    "created_at" timestamp with time zone DEFAULT now(),
    "marked_by" character varying DEFAULT 'qr'::character varying
);

CREATE TABLE "public"."student_houses" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "name" character varying NOT NULL,
    "color" character varying DEFAULT '#ffa500'::character varying,
    "motto" text,
    "description" text,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."student_issued_items" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "student_id" uuid,
    "item_id" uuid,
    "quantity" integer DEFAULT 1 NOT NULL,
    "issue_date" date NOT NULL,
    "reason" text,
    "created_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."student_promotions" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "student_id" uuid,
    "from_class_id" uuid,
    "to_class_id" uuid,
    "promotion_date" date NOT NULL,
    "academic_year" integer,
    "created_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."student_requirements" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "student_id" uuid NOT NULL,
    "item_id" uuid NOT NULL,
    "quantity_brought" numeric NOT NULL,
    "date_submitted" date DEFAULT CURRENT_DATE NOT NULL,
    "received_by" uuid NOT NULL,
    "notes" text,
    "created_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."students" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "student_id" character varying NOT NULL,
    "name" character varying NOT NULL,
    "gender" character varying,
    "date_of_birth" date,
    "nationality" character varying,
    "address" text,
    "contact_number" character varying,
    "email" character varying,
    "father_name" character varying,
    "mother_name" character varying,
    "religion" character varying,
    "occupation" character varying,
    "reason_for_admission" text,
    "all_parents" character varying,
    "class_id" uuid,
    "photo_url" text,
    "photo_public_id" text,
    "status" character varying DEFAULT 'active'::character varying,
    "enrollment_date" date,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    "category" character varying,
    "student_house_id" uuid
);

CREATE TABLE "public"."subjects" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid,
    "name" character varying NOT NULL,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."subscriptions" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "start_date" date NOT NULL,
    "expiry_date" date NOT NULL,
    "status" character varying DEFAULT 'active'::character varying,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."whatsapp_auth" (
    "id" integer DEFAULT nextval('whatsapp_auth_id_seq'::regclass) NOT NULL,
    "session_id" character varying DEFAULT 'default'::character varying NOT NULL,
    "creds" jsonb NOT NULL,
    "keys" jsonb NOT NULL,
    "created_at" timestamp without time zone DEFAULT now(),
    "updated_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."whatsapp_auth_files" (
    "id" integer DEFAULT nextval('whatsapp_auth_files_id_seq'::regclass) NOT NULL,
    "filename" character varying NOT NULL,
    "content" text NOT NULL,
    "created_at" timestamp without time zone DEFAULT now(),
    "updated_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."whatsapp_auth_files_custom" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "filename" character varying NOT NULL,
    "content" text NOT NULL,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."whatsapp_auth_files_global" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "filename" text NOT NULL,
    "content" text NOT NULL,
    "updated_at" timestamp with time zone DEFAULT now()
);

CREATE TABLE "public"."whatsapp_sessions" (
    "id" integer DEFAULT nextval('whatsapp_sessions_id_seq'::regclass) NOT NULL,
    "session_id" character varying DEFAULT 'default'::character varying NOT NULL,
    "creds" jsonb NOT NULL,
    "created_at" timestamp without time zone DEFAULT now(),
    "updated_at" timestamp without time zone DEFAULT now()
);

CREATE TABLE "public"."whatsapp_settings_custom" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "institute_id" uuid NOT NULL,
    "nodejs_api_url" character varying,
    "api_key" character varying,
    "is_enabled" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now()
);


-- ============================================================
-- CONSTRAINTS
-- ============================================================

ALTER TABLE ONLY "public"."academic_terms" ADD CONSTRAINT "academic_terms_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."advance_payments" ADD CONSTRAINT "advance_payments_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."agent_applications" ADD CONSTRAINT "agent_applications_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."agent_submissions" ADD CONSTRAINT "agent_submissions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."agent_tasks" ADD CONSTRAINT "agent_tasks_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."agents" ADD CONSTRAINT "agents_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."asset_transactions" ADD CONSTRAINT "asset_transactions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."attendance" ADD CONSTRAINT "attendance_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."budget_headers" ADD CONSTRAINT "budget_headers_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."budget_lines" ADD CONSTRAINT "budget_lines_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."budgets" ADD CONSTRAINT "budgets_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."cdc_report_settings" ADD CONSTRAINT "cdc_report_settings_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."chart_of_accounts" ADD CONSTRAINT "chart_of_accounts_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."class_enrollments" ADD CONSTRAINT "class_enrollments_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."class_requirements" ADD CONSTRAINT "class_requirements_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."class_sections" ADD CONSTRAINT "class_sections_pkey" PRIMARY KEY (class_id, section_id);
ALTER TABLE ONLY "public"."class_subjects" ADD CONSTRAINT "class_subjects_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."classes" ADD CONSTRAINT "classes_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."discounts" ADD CONSTRAINT "discounts_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."division_rules" ADD CONSTRAINT "division_rules_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."employee_advances" ADD CONSTRAINT "employee_advances_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."employee_permissions" ADD CONSTRAINT "employee_permissions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."employees" ADD CONSTRAINT "employees_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."exam_fail_criteria" ADD CONSTRAINT "exam_fail_criteria_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."exam_grading" ADD CONSTRAINT "exam_grading_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."exam_grading_requirements" ADD CONSTRAINT "exam_grading_requirements_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."exam_marks" ADD CONSTRAINT "exam_marks_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."exam_marks_history" ADD CONSTRAINT "exam_marks_history_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."exam_marksheets" ADD CONSTRAINT "exam_marksheets_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."exams" ADD CONSTRAINT "exams_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."expense_transactions" ADD CONSTRAINT "expense_transactions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."fee_names" ADD CONSTRAINT "fee_names_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."fee_particulars" ADD CONSTRAINT "fee_particulars_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."income_transactions" ADD CONSTRAINT "income_transactions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."institutes" ADD CONSTRAINT "institutes_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."inventory" ADD CONSTRAINT "inventory_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."inventory_transactions" ADD CONSTRAINT "inventory_transactions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."invoices" ADD CONSTRAINT "invoices_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."liability_transactions" ADD CONSTRAINT "liability_transactions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."manual_payment_requests" ADD CONSTRAINT "manual_payment_requests_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."message_logs" ADD CONSTRAINT "message_logs_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."next_term_settings" ADD CONSTRAINT "next_term_settings_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."organization_billing" ADD CONSTRAINT "organization_billing_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."payment_transactions" ADD CONSTRAINT "payment_transactions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."payments" ADD CONSTRAINT "payments_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."report_templates" ADD CONSTRAINT "report_templates_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."requirement_items" ADD CONSTRAINT "requirement_items_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."role_permissions" ADD CONSTRAINT "role_permissions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."salary_payments" ADD CONSTRAINT "salary_payments_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."schoolpay_accounts" ADD CONSTRAINT "schoolpay_accounts_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."schoolpay_settings" ADD CONSTRAINT "schoolpay_settings_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."sections" ADD CONSTRAINT "sections_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."sms_credits" ADD CONSTRAINT "sms_credits_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."sms_log" ADD CONSTRAINT "sms_log_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."sms_payment_transactions" ADD CONSTRAINT "sms_payment_transactions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."sms_sent_log" ADD CONSTRAINT "sms_sent_log_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."sms_settings" ADD CONSTRAINT "sms_settings_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."staff_attendance" ADD CONSTRAINT "staff_attendance_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."student_houses" ADD CONSTRAINT "student_houses_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."student_issued_items" ADD CONSTRAINT "student_issued_items_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."student_promotions" ADD CONSTRAINT "student_promotions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."student_requirements" ADD CONSTRAINT "student_requirements_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."students" ADD CONSTRAINT "students_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."subjects" ADD CONSTRAINT "subjects_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."subscriptions" ADD CONSTRAINT "subscriptions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."whatsapp_auth" ADD CONSTRAINT "whatsapp_auth_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."whatsapp_auth_files" ADD CONSTRAINT "whatsapp_auth_files_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."whatsapp_auth_files_custom" ADD CONSTRAINT "whatsapp_auth_files_custom_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."whatsapp_auth_files_global" ADD CONSTRAINT "whatsapp_auth_files_global_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."whatsapp_sessions" ADD CONSTRAINT "whatsapp_sessions_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."whatsapp_settings_custom" ADD CONSTRAINT "whatsapp_settings_custom_pkey" PRIMARY KEY (id);
ALTER TABLE ONLY "public"."cdc_report_settings" ADD CONSTRAINT "cdc_report_settings_institute_id_key" UNIQUE (institute_id);
ALTER TABLE ONLY "public"."chart_of_accounts" ADD CONSTRAINT "chart_of_accounts_account_code_key" UNIQUE (account_code);
ALTER TABLE ONLY "public"."employee_permissions" ADD CONSTRAINT "employee_permissions_employee_id_key" UNIQUE (employee_id);
ALTER TABLE ONLY "public"."employees" ADD CONSTRAINT "employees_employee_id_key" UNIQUE (employee_id);
ALTER TABLE ONLY "public"."exam_fail_criteria" ADD CONSTRAINT "exam_fail_criteria_institute_id_key" UNIQUE (institute_id);
ALTER TABLE ONLY "public"."exam_grading_requirements" ADD CONSTRAINT "exam_grading_requirements_institute_id_key" UNIQUE (institute_id);
ALTER TABLE ONLY "public"."exam_marksheets" ADD CONSTRAINT "exam_marksheets_marksheet_number_key" UNIQUE (marksheet_number);
ALTER TABLE ONLY "public"."institutes" ADD CONSTRAINT "institutes_institute_code_key" UNIQUE (institute_code);
ALTER TABLE ONLY "public"."invoices" ADD CONSTRAINT "invoices_invoice_number_key" UNIQUE (invoice_number);
ALTER TABLE ONLY "public"."next_term_settings" ADD CONSTRAINT "next_term_settings_institute_id_key" UNIQUE (institute_id);
ALTER TABLE ONLY "public"."organization_billing" ADD CONSTRAINT "organization_billing_institute_id_key" UNIQUE (institute_id);
ALTER TABLE ONLY "public"."payments" ADD CONSTRAINT "payments_receipt_number_key" UNIQUE (receipt_number);
ALTER TABLE ONLY "public"."role_permissions" ADD CONSTRAINT "role_permissions_institute_id_role_key" UNIQUE (institute_id, role);
ALTER TABLE ONLY "public"."salary_payments" ADD CONSTRAINT "salary_payments_receipt_number_key" UNIQUE (receipt_number);
ALTER TABLE ONLY "public"."schoolpay_settings" ADD CONSTRAINT "schoolpay_settings_institute_id_key" UNIQUE (institute_id);
ALTER TABLE ONLY "public"."sms_credits" ADD CONSTRAINT "sms_credits_institute_id_key" UNIQUE (institute_id);
ALTER TABLE ONLY "public"."sms_settings" ADD CONSTRAINT "sms_settings_institute_id_key" UNIQUE (institute_id);
ALTER TABLE ONLY "public"."students" ADD CONSTRAINT "students_student_id_key" UNIQUE (student_id);
ALTER TABLE ONLY "public"."subscriptions" ADD CONSTRAINT "subscriptions_institute_id_key" UNIQUE (institute_id);
ALTER TABLE ONLY "public"."whatsapp_auth" ADD CONSTRAINT "whatsapp_auth_session_id_key" UNIQUE (session_id);
ALTER TABLE ONLY "public"."whatsapp_auth_files" ADD CONSTRAINT "whatsapp_auth_files_filename_key" UNIQUE (filename);
ALTER TABLE ONLY "public"."whatsapp_sessions" ADD CONSTRAINT "whatsapp_sessions_session_id_key" UNIQUE (session_id);
ALTER TABLE ONLY "public"."whatsapp_settings_custom" ADD CONSTRAINT "whatsapp_settings_custom_institute_id_key" UNIQUE (institute_id);
ALTER TABLE ONLY "public"."asset_transactions" ADD CONSTRAINT "asset_transactions_transaction_type_check" CHECK (transaction_type::text = ANY (ARRAY['debit'::character varying, 'credit'::character varying]::text[]));
ALTER TABLE ONLY "public"."budget_headers" ADD CONSTRAINT "budget_headers_period_type_check" CHECK (period_type = ANY (ARRAY['yearly'::text, 'quarterly'::text, 'monthly'::text]));
ALTER TABLE ONLY "public"."budget_headers" ADD CONSTRAINT "budget_headers_status_check" CHECK (status = ANY (ARRAY['draft'::text, 'approved'::text, 'archived'::text]));
ALTER TABLE ONLY "public"."inventory_transactions" ADD CONSTRAINT "inventory_transactions_transaction_type_check" CHECK (transaction_type::text = ANY (ARRAY['in'::character varying, 'out'::character varying]::text[]));
ALTER TABLE ONLY "public"."liability_transactions" ADD CONSTRAINT "liability_transactions_transaction_type_check" CHECK (transaction_type::text = ANY (ARRAY['debit'::character varying, 'credit'::character varying]::text[]));
ALTER TABLE ONLY "public"."academic_terms" ADD CONSTRAINT "academic_terms_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."advance_payments" ADD CONSTRAINT "advance_payments_advance_id_fkey" FOREIGN KEY (advance_id) REFERENCES employee_advances(id);
ALTER TABLE ONLY "public"."advance_payments" ADD CONSTRAINT "advance_payments_employee_id_fkey" FOREIGN KEY (employee_id) REFERENCES employees(id);
ALTER TABLE ONLY "public"."advance_payments" ADD CONSTRAINT "advance_payments_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."agent_submissions" ADD CONSTRAINT "agent_submissions_agent_id_fkey" FOREIGN KEY (agent_id) REFERENCES agents(id);
ALTER TABLE ONLY "public"."agent_submissions" ADD CONSTRAINT "agent_submissions_task_id_fkey" FOREIGN KEY (task_id) REFERENCES agent_tasks(id);
ALTER TABLE ONLY "public"."agents" ADD CONSTRAINT "agents_application_id_fkey" FOREIGN KEY (application_id) REFERENCES agent_applications(id);
ALTER TABLE ONLY "public"."asset_transactions" ADD CONSTRAINT "asset_transactions_account_id_fkey" FOREIGN KEY (account_id) REFERENCES chart_of_accounts(id);
ALTER TABLE ONLY "public"."asset_transactions" ADD CONSTRAINT "asset_transactions_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."attendance" ADD CONSTRAINT "attendance_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."attendance" ADD CONSTRAINT "attendance_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."budget_headers" ADD CONSTRAINT "budget_headers_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."budget_lines" ADD CONSTRAINT "budget_lines_account_id_fkey" FOREIGN KEY (account_id) REFERENCES chart_of_accounts(id);
ALTER TABLE ONLY "public"."budget_lines" ADD CONSTRAINT "budget_lines_budget_header_id_fkey" FOREIGN KEY (budget_header_id) REFERENCES budget_headers(id);
ALTER TABLE ONLY "public"."budgets" ADD CONSTRAINT "budgets_account_id_fkey" FOREIGN KEY (account_id) REFERENCES chart_of_accounts(id);
ALTER TABLE ONLY "public"."budgets" ADD CONSTRAINT "budgets_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."cdc_report_settings" ADD CONSTRAINT "cdc_report_settings_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."chart_of_accounts" ADD CONSTRAINT "chart_of_accounts_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."class_enrollments" ADD CONSTRAINT "class_enrollments_class_id_fkey" FOREIGN KEY (class_id) REFERENCES classes(id);
ALTER TABLE ONLY "public"."class_enrollments" ADD CONSTRAINT "class_enrollments_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."class_requirements" ADD CONSTRAINT "class_requirements_class_id_fkey" FOREIGN KEY (class_id) REFERENCES classes(id);
ALTER TABLE ONLY "public"."class_requirements" ADD CONSTRAINT "class_requirements_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."class_requirements" ADD CONSTRAINT "class_requirements_item_id_fkey" FOREIGN KEY (item_id) REFERENCES requirement_items(id);
ALTER TABLE ONLY "public"."class_requirements" ADD CONSTRAINT "class_requirements_term_id_fkey" FOREIGN KEY (term_id) REFERENCES academic_terms(id);
ALTER TABLE ONLY "public"."class_sections" ADD CONSTRAINT "class_sections_class_id_fkey" FOREIGN KEY (class_id) REFERENCES classes(id);
ALTER TABLE ONLY "public"."class_sections" ADD CONSTRAINT "class_sections_section_id_fkey" FOREIGN KEY (section_id) REFERENCES sections(id);
ALTER TABLE ONLY "public"."class_subjects" ADD CONSTRAINT "class_subjects_class_id_fkey" FOREIGN KEY (class_id) REFERENCES classes(id);
ALTER TABLE ONLY "public"."class_subjects" ADD CONSTRAINT "class_subjects_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."class_subjects" ADD CONSTRAINT "class_subjects_subject_id_fkey" FOREIGN KEY (subject_id) REFERENCES subjects(id);
ALTER TABLE ONLY "public"."class_subjects" ADD CONSTRAINT "class_subjects_teacher_id_fkey" FOREIGN KEY (teacher_id) REFERENCES employees(id);
ALTER TABLE ONLY "public"."classes" ADD CONSTRAINT "classes_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."discounts" ADD CONSTRAINT "discounts_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."discounts" ADD CONSTRAINT "discounts_invoice_id_fkey" FOREIGN KEY (invoice_id) REFERENCES invoices(id);
ALTER TABLE ONLY "public"."discounts" ADD CONSTRAINT "discounts_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."division_rules" ADD CONSTRAINT "division_rules_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."employee_advances" ADD CONSTRAINT "employee_advances_approved_by_fkey" FOREIGN KEY (approved_by) REFERENCES auth.users(id);
ALTER TABLE ONLY "public"."employee_advances" ADD CONSTRAINT "employee_advances_employee_id_fkey" FOREIGN KEY (employee_id) REFERENCES employees(id);
ALTER TABLE ONLY "public"."employee_advances" ADD CONSTRAINT "employee_advances_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."employee_permissions" ADD CONSTRAINT "employee_permissions_employee_id_fkey" FOREIGN KEY (employee_id) REFERENCES employees(id);
ALTER TABLE ONLY "public"."employee_permissions" ADD CONSTRAINT "employee_permissions_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."employees" ADD CONSTRAINT "employees_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."exam_fail_criteria" ADD CONSTRAINT "exam_fail_criteria_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."exam_grading" ADD CONSTRAINT "exam_grading_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."exam_grading_requirements" ADD CONSTRAINT "exam_grading_requirements_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."exam_marks" ADD CONSTRAINT "exam_marks_class_id_fkey" FOREIGN KEY (class_id) REFERENCES classes(id);
ALTER TABLE ONLY "public"."exam_marks" ADD CONSTRAINT "exam_marks_exam_id_fkey" FOREIGN KEY (exam_id) REFERENCES exams(id);
ALTER TABLE ONLY "public"."exam_marks" ADD CONSTRAINT "exam_marks_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."exam_marks" ADD CONSTRAINT "exam_marks_marksheet_id_fkey" FOREIGN KEY (marksheet_id) REFERENCES exam_marksheets(id);
ALTER TABLE ONLY "public"."exam_marks" ADD CONSTRAINT "exam_marks_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."exam_marks" ADD CONSTRAINT "exam_marks_subject_id_fkey" FOREIGN KEY (subject_id) REFERENCES subjects(id);
ALTER TABLE ONLY "public"."exam_marks_history" ADD CONSTRAINT "exam_marks_history_class_id_fkey" FOREIGN KEY (class_id) REFERENCES classes(id);
ALTER TABLE ONLY "public"."exam_marks_history" ADD CONSTRAINT "exam_marks_history_exam_id_fkey" FOREIGN KEY (exam_id) REFERENCES exams(id);
ALTER TABLE ONLY "public"."exam_marks_history" ADD CONSTRAINT "exam_marks_history_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."exam_marks_history" ADD CONSTRAINT "exam_marks_history_marksheet_id_fkey" FOREIGN KEY (marksheet_id) REFERENCES exam_marksheets(id);
ALTER TABLE ONLY "public"."exam_marks_history" ADD CONSTRAINT "exam_marks_history_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."exam_marks_history" ADD CONSTRAINT "exam_marks_history_subject_id_fkey" FOREIGN KEY (subject_id) REFERENCES subjects(id);
ALTER TABLE ONLY "public"."exam_marksheets" ADD CONSTRAINT "exam_marksheets_class_id_fkey" FOREIGN KEY (class_id) REFERENCES classes(id);
ALTER TABLE ONLY "public"."exam_marksheets" ADD CONSTRAINT "exam_marksheets_exam_id_fkey" FOREIGN KEY (exam_id) REFERENCES exams(id);
ALTER TABLE ONLY "public"."exam_marksheets" ADD CONSTRAINT "exam_marksheets_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."exams" ADD CONSTRAINT "exams_class_id_fkey" FOREIGN KEY (class_id) REFERENCES classes(id);
ALTER TABLE ONLY "public"."exams" ADD CONSTRAINT "exams_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."expense_transactions" ADD CONSTRAINT "expense_transactions_account_id_fkey" FOREIGN KEY (account_id) REFERENCES chart_of_accounts(id);
ALTER TABLE ONLY "public"."expense_transactions" ADD CONSTRAINT "expense_transactions_employee_id_fkey" FOREIGN KEY (employee_id) REFERENCES employees(id);
ALTER TABLE ONLY "public"."expense_transactions" ADD CONSTRAINT "expense_transactions_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."fee_names" ADD CONSTRAINT "fee_names_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."fee_particulars" ADD CONSTRAINT "fee_particulars_class_id_fkey" FOREIGN KEY (class_id) REFERENCES classes(id);
ALTER TABLE ONLY "public"."fee_particulars" ADD CONSTRAINT "fee_particulars_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."fee_particulars" ADD CONSTRAINT "fee_particulars_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."income_transactions" ADD CONSTRAINT "income_transactions_account_id_fkey" FOREIGN KEY (account_id) REFERENCES chart_of_accounts(id);
ALTER TABLE ONLY "public"."income_transactions" ADD CONSTRAINT "income_transactions_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."institutes" ADD CONSTRAINT "institutes_user_id_fkey" FOREIGN KEY (user_id) REFERENCES auth.users(id);
ALTER TABLE ONLY "public"."inventory" ADD CONSTRAINT "inventory_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."inventory_transactions" ADD CONSTRAINT "inventory_transactions_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."inventory_transactions" ADD CONSTRAINT "inventory_transactions_item_id_fkey" FOREIGN KEY (item_id) REFERENCES requirement_items(id);
ALTER TABLE ONLY "public"."invoices" ADD CONSTRAINT "invoices_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."invoices" ADD CONSTRAINT "invoices_particulars_id_fkey" FOREIGN KEY (particulars_id) REFERENCES fee_particulars(id);
ALTER TABLE ONLY "public"."invoices" ADD CONSTRAINT "invoices_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."liability_transactions" ADD CONSTRAINT "liability_transactions_account_id_fkey" FOREIGN KEY (account_id) REFERENCES chart_of_accounts(id);
ALTER TABLE ONLY "public"."liability_transactions" ADD CONSTRAINT "liability_transactions_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."manual_payment_requests" ADD CONSTRAINT "manual_payment_requests_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."message_logs" ADD CONSTRAINT "message_logs_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."next_term_settings" ADD CONSTRAINT "next_term_settings_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."organization_billing" ADD CONSTRAINT "organization_billing_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."payment_transactions" ADD CONSTRAINT "payment_transactions_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."payments" ADD CONSTRAINT "payments_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."payments" ADD CONSTRAINT "payments_invoice_id_fkey" FOREIGN KEY (invoice_id) REFERENCES invoices(id);
ALTER TABLE ONLY "public"."payments" ADD CONSTRAINT "payments_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."report_templates" ADD CONSTRAINT "report_templates_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."requirement_items" ADD CONSTRAINT "requirement_items_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."role_permissions" ADD CONSTRAINT "role_permissions_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id) ON DELETE CASCADE;
ALTER TABLE ONLY "public"."salary_payments" ADD CONSTRAINT "salary_payments_employee_id_fkey" FOREIGN KEY (employee_id) REFERENCES employees(id);
ALTER TABLE ONLY "public"."salary_payments" ADD CONSTRAINT "salary_payments_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."schoolpay_accounts" ADD CONSTRAINT "schoolpay_accounts_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."schoolpay_settings" ADD CONSTRAINT "schoolpay_settings_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."sections" ADD CONSTRAINT "sections_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."sms_credits" ADD CONSTRAINT "sms_credits_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."sms_log" ADD CONSTRAINT "sms_log_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."sms_log" ADD CONSTRAINT "sms_log_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."sms_payment_transactions" ADD CONSTRAINT "sms_payment_transactions_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."sms_sent_log" ADD CONSTRAINT "sms_sent_log_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."sms_sent_log" ADD CONSTRAINT "sms_sent_log_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."sms_settings" ADD CONSTRAINT "sms_settings_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."staff_attendance" ADD CONSTRAINT "staff_attendance_employee_id_fkey" FOREIGN KEY (employee_id) REFERENCES employees(id);
ALTER TABLE ONLY "public"."staff_attendance" ADD CONSTRAINT "staff_attendance_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."student_houses" ADD CONSTRAINT "student_houses_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."student_issued_items" ADD CONSTRAINT "student_issued_items_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."student_issued_items" ADD CONSTRAINT "student_issued_items_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."student_promotions" ADD CONSTRAINT "student_promotions_from_class_id_fkey" FOREIGN KEY (from_class_id) REFERENCES classes(id);
ALTER TABLE ONLY "public"."student_promotions" ADD CONSTRAINT "student_promotions_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."student_promotions" ADD CONSTRAINT "student_promotions_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."student_promotions" ADD CONSTRAINT "student_promotions_to_class_id_fkey" FOREIGN KEY (to_class_id) REFERENCES classes(id);
ALTER TABLE ONLY "public"."student_requirements" ADD CONSTRAINT "student_requirements_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."student_requirements" ADD CONSTRAINT "student_requirements_item_id_fkey" FOREIGN KEY (item_id) REFERENCES requirement_items(id);
ALTER TABLE ONLY "public"."student_requirements" ADD CONSTRAINT "student_requirements_student_id_fkey" FOREIGN KEY (student_id) REFERENCES students(id);
ALTER TABLE ONLY "public"."students" ADD CONSTRAINT "students_class_id_fkey" FOREIGN KEY (class_id) REFERENCES classes(id);
ALTER TABLE ONLY "public"."students" ADD CONSTRAINT "students_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."students" ADD CONSTRAINT "students_student_house_id_fkey" FOREIGN KEY (student_house_id) REFERENCES student_houses(id);
ALTER TABLE ONLY "public"."subjects" ADD CONSTRAINT "subjects_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."subscriptions" ADD CONSTRAINT "subscriptions_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."whatsapp_auth_files_custom" ADD CONSTRAINT "whatsapp_auth_files_custom_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);
ALTER TABLE ONLY "public"."whatsapp_settings_custom" ADD CONSTRAINT "whatsapp_settings_custom_institute_id_fkey" FOREIGN KEY (institute_id) REFERENCES institutes(id);


-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX idx_agent_submissions_agent_id ON public.agent_submissions USING btree (agent_id);
CREATE INDEX idx_agent_submissions_task_id ON public.agent_submissions USING btree (task_id);
CREATE INDEX idx_agents_region ON public.agents USING btree (region);
CREATE INDEX idx_attendance_scan_date ON public.attendance USING btree (scan_date);
CREATE INDEX idx_attendance_student_id ON public.attendance USING btree (student_id);
CREATE INDEX idx_chart_of_accounts_institute_id ON public.chart_of_accounts USING btree (institute_id);
CREATE INDEX idx_classes_institute_id ON public.classes USING btree (institute_id);
CREATE INDEX idx_employees_institute_id ON public.employees USING btree (institute_id);
CREATE INDEX idx_employees_status ON public.employees USING btree (status);
CREATE INDEX idx_exam_marks_exam_id ON public.exam_marks USING btree (exam_id);
CREATE INDEX idx_exam_marks_student_id ON public.exam_marks USING btree (student_id);
CREATE INDEX idx_exams_class_id ON public.exams USING btree (class_id);
CREATE INDEX idx_exams_institute_id ON public.exams USING btree (institute_id);
CREATE INDEX idx_expense_transactions_institute_id ON public.expense_transactions USING btree (institute_id);
CREATE INDEX idx_income_transactions_institute_id ON public.income_transactions USING btree (institute_id);
CREATE INDEX idx_institutes_code ON public.institutes USING btree (institute_code);
CREATE INDEX idx_institutes_status ON public.institutes USING btree (status);
CREATE INDEX idx_institutes_user_id ON public.institutes USING btree (user_id);
CREATE INDEX idx_inventory_transactions_institute_id ON public.inventory_transactions USING btree (institute_id);
CREATE INDEX idx_inventory_transactions_item_id ON public.inventory_transactions USING btree (item_id);
CREATE INDEX idx_invoices_institute_id ON public.invoices USING btree (institute_id);
CREATE INDEX idx_invoices_status ON public.invoices USING btree (status);
CREATE INDEX idx_invoices_student_id ON public.invoices USING btree (student_id);
CREATE INDEX idx_payments_invoice_id ON public.payments USING btree (invoice_id);
CREATE INDEX idx_payments_student_id ON public.payments USING btree (student_id);
CREATE INDEX idx_role_perms_institute ON public.role_permissions USING btree (institute_id);
CREATE INDEX idx_sections_institute_id ON public.sections USING btree (institute_id);
CREATE INDEX idx_sms_sent_log_institute_id ON public.sms_sent_log USING btree (institute_id);
CREATE INDEX idx_sms_sent_log_sent_at ON public.sms_sent_log USING btree (sent_at);
CREATE INDEX idx_staff_attendance_employee_id ON public.staff_attendance USING btree (employee_id);
CREATE INDEX idx_students_class_id ON public.students USING btree (class_id);
CREATE INDEX idx_students_institute_id ON public.students USING btree (institute_id);
CREATE INDEX idx_students_status ON public.students USING btree (status);
CREATE INDEX idx_students_student_house_id ON public.students USING btree (student_house_id);
CREATE INDEX idx_whatsapp_auth_global_filename ON public.whatsapp_auth_files_global USING btree (filename);


-- ============================================================
-- FUNCTIONS
-- ============================================================


-- ============================================================
-- TRIGGERS
-- ============================================================



-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE "public"."academic_terms" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."advance_payments" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."agent_applications" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."agent_submissions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."agent_tasks" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."agents" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."asset_transactions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."attendance" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."budget_headers" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."budget_lines" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."budgets" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."cdc_report_settings" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."chart_of_accounts" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."class_enrollments" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."class_requirements" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."class_sections" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."class_subjects" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."classes" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."discounts" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."division_rules" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."employee_advances" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."employee_permissions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."employees" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."exam_fail_criteria" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."exam_grading" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."exam_grading_requirements" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."exam_marks" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."exam_marks_history" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."exam_marksheets" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."exams" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."expense_transactions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."fee_names" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."fee_particulars" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."income_transactions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."institutes" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."inventory" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."inventory_transactions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."invoices" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."liability_transactions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."manual_payment_requests" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."message_logs" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."next_term_settings" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."organization_billing" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."payment_transactions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."payments" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."report_templates" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."requirement_items" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."role_permissions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."salary_payments" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."schoolpay_accounts" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."schoolpay_settings" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."sections" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."sms_credits" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."sms_log" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."sms_payment_transactions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."sms_sent_log" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."sms_settings" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."staff_attendance" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."student_houses" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."student_issued_items" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."student_promotions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."student_requirements" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."students" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."subjects" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."subscriptions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."whatsapp_auth" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."whatsapp_auth_files" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."whatsapp_auth_files_custom" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."whatsapp_auth_files_global" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."whatsapp_sessions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."whatsapp_settings_custom" ENABLE ROW LEVEL SECURITY;


-- ============================================================
-- RLS POLICIES
-- ============================================================

CREATE POLICY "Service role full access" ON "public"."role_permissions" AS PERMISSIVE FOR ALL TO PUBLIC USING (true) WITH CHECK (true);


-- ============================================================
-- VIEWS
-- ============================================================

COMMIT;

-- ============================================================
-- END OF SUPABASE EXPORT
-- ============================================================