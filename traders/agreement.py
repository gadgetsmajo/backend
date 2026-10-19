from django.conf import settings


AGREEMENT_VERSION = '1.0'
AGREEMENT_SECTIONS = [
    ('1. PARTIES TO THE AGREEMENT', [
        'This Agreement is entered into between Majo Gadgets, operated by {operator}, of {operator_address}, Uganda, hereinafter referred to as "Majo Gadgets"; and Trader Name: {trader_name}; Trader ID: {trader_id}; Business Name: {business_name}; Address: {trader_address}; Email: {email}; hereinafter referred to as "the Trader." Together, they are referred to as "the Parties."',
    ]),
    ('2. PURPOSE AND APPOINTMENT', [
        '2.1. Majo Gadgets appoints the Trader, subject to this Agreement, to list and sell approved products through its online marketplace.',
        '2.2. The Trader accepts this appointment and agrees to comply with this Agreement, applicable marketplace policies, and the laws of Uganda.',
        '2.3. Admin approval does not authorize selling until the Trader has signed this Agreement and Majo Gadgets has activated the account.',
    ]),
    ('3. TRADER OBLIGATIONS', [
        'The Trader shall:',
        'a. Provide accurate registration, verification, tax, and payment information.',
        'b. Sell only genuine, lawful, and appropriately sourced products.',
        'c. Ensure product descriptions, images, specifications, prices, stock quantities, and warranties are accurate.',
        'd. Maintain appropriate product quality, packaging, and stock records.',
        'e. Fulfil accepted orders accurately and within the applicable timelines.',
        'f. Cooperate with inspections, investigations, returns, and other authorized marketplace processes.',
        'g. Refrain from fraud, misleading representations, fake reviews, counterfeit sales, and manipulation of orders or marketplace records.',
    ]),
    ('4. CUSTOMER PRIVACY AND COMMUNICATION', [
        '4.1. Majo Gadgets exclusively manages customer communication through its designated channels.',
        '4.2. The Trader shall not directly contact customers, request their personal details, access restricted customer information, or attempt to identify them.',
        '4.3. The Trader shall not divert customers to private transactions or use packaging, promotional materials, or other means to bypass Majo Gadgets.',
        '4.4. All customer enquiries, complaints, returns, refunds, and disputes must be handled through Majo Gadgets.',
        '4.5. A breach of this clause may result in immediate account restriction, suspension, or termination, depending on the severity of the breach.',
    ]),
    ('5. PRODUCT RETURNS AND QUALITY CONTROL', [
        '5.1. Majo Gadgets shall manage the official customer return and refund process in accordance with its policies and applicable law.',
        '5.2. Where the same product associated with the same Trader receives more than three recorded returns, the Trader account shall be temporarily disabled pending investigation, with the fourth recorded return triggering the restriction.',
        '5.3. Majo Gadgets shall investigate the relevant return reasons and may require corrective action before reinstating the account.',
        '5.4. Fraud, counterfeit products, deliberate misrepresentation, or serious safety concerns may justify immediate suspension regardless of return count.',
        '5.5. Return decisions shall consider available evidence and applicable customer rights. This clause does not remove any statutory consumer protection rights.',
    ]),
    ('6. COMMISSIONS, PAYMENTS AND SETTLEMENTS', [
        '6.1. The Trader agrees to the commission rates, fees, payout schedules, and settlement procedures separately disclosed and accepted by the Trader.',
        '6.2. The Trader shall maintain accurate payout details and comply with applicable tax obligations.',
        '6.3. Refunds, reversals, deductions, and disputed settlements shall be handled under the agreed payment policies and applicable law.',
        '6.4. Neither Party may impose an undisclosed fee or deduction contrary to the applicable agreement or law.',
    ]),
    ('7. CONFIDENTIALITY AND DATA PROTECTION', [
        '7.1. Each Party shall protect confidential information received through this relationship.',
        '7.2. The Trader shall not collect, disclose, retain, or misuse customer personal information.',
        '7.3. Both Parties shall comply with applicable data protection and privacy obligations.',
        '7.4. These obligations continue after termination to the extent required by law or the nature of the information.',
    ]),
    ('8. BREACH AND REMEDIES', [
        '8.1. Where a Party breaches this Agreement, the other Party may take reasonable action permitted by this Agreement and applicable law.',
        '8.2. Depending on the circumstances, Majo Gadgets may issue a warning, remove a listing, restrict selling privileges, suspend the Trader, or terminate this Agreement.',
        '8.3. Where appropriate and legally permitted, the Trader shall be informed of the grounds for significant restrictions and may request a review.',
        '8.4. Each Party remains responsible for its own unlawful conduct and obligations under applicable law.',
    ]),
    ('9. TERM AND TERMINATION', [
        '9.1. This Agreement commences when both Parties have executed it and the Trader\'s account has been activated.',
        '9.2. Either Party may seek to terminate the relationship by giving written notice through the agreed communication channel, subject to outstanding orders, payment obligations, returns, and applicable law.',
        '9.3. Majo Gadgets may suspend or terminate the Agreement for serious misconduct, fraud, repeated violations, or other lawful grounds.',
        '9.4. Termination does not extinguish accrued rights, outstanding payment obligations, or provisions intended to survive termination.',
    ]),
    ('10. LIABILITY AND DISPUTES', [
        '10.1. Each Party shall be responsible for its own acts, omissions, and contractual obligations.',
        '10.2. Neither Party shall be liable for matters excluded by applicable law from contractual limitation or exclusion.',
        '10.3. The Parties shall first attempt to resolve disputes through good-faith written communication.',
        '10.4. If a dispute remains unresolved, either Party may pursue mediation or proceedings before a competent Ugandan court, subject to applicable law.',
    ]),
    ('11. GOVERNING LAW', [
        'This Agreement shall be governed by the laws of Uganda, subject to applicable mandatory legal requirements.',
    ]),
    ('12. ENTIRE AGREEMENT AND AMENDMENTS', [
        '12.1. This Agreement, together with the policies expressly incorporated into it, constitutes the agreement between the Parties concerning the Trader\'s participation in Majo Gadgets.',
        '12.2. Any amendment must be communicated and accepted in accordance with applicable contractual requirements and law.',
        '12.3. If any provision is held unenforceable, the remaining provisions shall continue to apply to the extent permitted by law.',
    ]),
    ('13. DECLARATION AND SIGNATURES', [
        'By signing below, each Party confirms that it has authority to enter into this Agreement, has read and understood its terms, and agrees to be legally bound by them.',
    ]),
]


def build_agreement_document(application):
    operator = settings.MAJO_LEGAL_OPERATOR_NAME
    address = settings.MAJO_BUSINESS_ADDRESS.strip()
    trader_id = application.agreement_reference or f'MG-TRADER-{application.pk:06d}'
    substitutions = {
        'operator': operator,
        'operator_address': address or '[Majo Gadgets registered business address required]',
        'trader_address': application.location,
        'trader_name': application.full_name,
        'trader_id': trader_id,
        'business_name': application.business_name,
        'email': application.email,
    }
    sections = [
        {'title': title, 'paragraphs': [paragraph.format(**substitutions) for paragraph in paragraphs]}
        for title, paragraphs in AGREEMENT_SECTIONS
    ]
    return {
        'title': 'Majo Gadgets Trader Participation and Marketplace Agreement',
        'reference': trader_id,
        'version': application.agreement_version or AGREEMENT_VERSION,
        'issued_at': application.agreement_issued_at,
        'effective_at': application.agreement_signed_at,
        'ready_to_sign': bool(address),
        'platform': {
            'name': 'Majo Gadgets',
            'operator': operator,
            'address': address,
            'signatory': operator,
            'title': settings.MAJO_LEGAL_OPERATOR_TITLE,
            'signed_at': application.reviewed_at,
        },
        'trader': {
            'name': application.full_name,
            'id': trader_id,
            'application_uuid': str(application.uuid),
            'business_name': application.business_name,
            'address': application.location,
            'email': application.email,
            'national_id': application.national_id,
            'registration_number': application.business_reg_no,
            'signed_name': application.agreement_signed_name,
            'signed_at': application.agreement_signed_at,
            'has_signature_image': bool(application.agreement_signature_image),
        },
        'sections': sections,
        'declaration': sections[-1]['paragraphs'][0],
        'id_document_included': False,
    }