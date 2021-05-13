import asyncio
import pytest

from asynctest import mock as async_mock
from copy import deepcopy

from .....core.in_memory import InMemoryProfile
from .....did.did_key import DIDKey
from .....resolver.did_resolver_registry import DIDResolverRegistry
from .....resolver.did_resolver import DIDResolver
from .....storage.vc_holder.vc_record import VCRecord
from .....wallet.base import BaseWallet
from .....wallet.crypto import KeyType
from .....wallet.did_method import DIDMethod
from .....wallet.error import WalletNotFoundError
from .....vc.ld_proofs import (
    BbsBlsSignatureProof2020,
)
from .....vc.ld_proofs.document_loader import DocumentLoader
from .....vc.ld_proofs.error import LinkedDataProofException
from .....vc.tests.document_loader import custom_document_loader
from .....vc.tests.data import (
    BBS_SIGNED_VC_MATTR,
    BBS_NESTED_VC_REVEAL_DOCUMENT_MATTR,
)

from ..pres_exch import (
    PresentationDefinition,
    Requirement,
    Filter,
    SchemaInputDescriptor,
    Constraints,
)
from ..pres_exch_handler import (
    DIFPresExchHandler,
    DIFPresExchError,
)

from .test_data import get_test_data, edd_jsonld_creds, bbs_bls_number_filter_creds


@pytest.yield_fixture(scope="class")
def event_loop(request):
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="class")
def profile():
    profile = InMemoryProfile.test_profile()
    context = profile.context
    did_resolver_registry = DIDResolverRegistry()
    context.injector.bind_instance(DIDResolverRegistry, did_resolver_registry)
    context.injector.bind_instance(DIDResolver, DIDResolver(did_resolver_registry))
    context.injector.bind_instance(DocumentLoader, custom_document_loader)
    return profile


@pytest.fixture(scope="class")
async def setup_tuple(profile):
    async with profile.session() as session:
        wallet = session.inject(BaseWallet, required=False)
        await wallet.create_local_did(
            method=DIDMethod.SOV, key_type=KeyType.ED25519, did="WgWxqztrNooG92RXvxSTWv"
        )
        creds, pds = get_test_data()
        return creds, pds


class TestPresExchHandler:
    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_load_cred_json_a(self, setup_tuple, profile):
        cred_list, pd_list = setup_tuple
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        # assert len(cred_list) == 6
        for tmp_pd in pd_list:
            # tmp_pd is tuple of presentation_definition and expected number of VCs
            tmp_vp = await dif_pres_exch_handler.create_vp(
                credentials=cred_list,
                pd=tmp_pd[0],
                challenge="1f44d55f-f161-4938-a659-f8026467f126",
            )
            assert len(tmp_vp.get("verifiableCredential")) == tmp_pd[1]

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_load_cred_json_b(self, setup_tuple, profile):
        cred_list, pd_list = setup_tuple
        dif_pres_exch_handler = DIFPresExchHandler(
            profile, pres_signing_did="did:sov:WgWxqztrNooG92RXvxSTWv"
        )
        # assert len(cred_list) == 6
        for tmp_pd in pd_list:
            # tmp_pd is tuple of presentation_definition and expected number of VCs
            tmp_vp = await dif_pres_exch_handler.create_vp(
                credentials=cred_list,
                pd=tmp_pd[0],
                challenge="1f44d55f-f161-4938-a659-f8026467f126",
            )
            assert len(tmp_vp.get("verifiableCredential")) == tmp_pd[1]

    @pytest.mark.asyncio
    async def test_to_requirement_catch_errors(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_json_pd = """
            {
                "submission_requirements": [
                    {
                        "name": "Banking Information",
                        "purpose": "We need you to prove you currently hold a bank account older than 12months.",
                        "rule": "pick",
                        "count": 1,
                        "from": "A"
                    }
                ],
                "id": "32f54163-7166-48f1-93d8-ff217bdb0653",
                "input_descriptors": [
                    {
                        "id": "banking_input_1",
                        "name": "Bank Account Information",
                        "purpose": "We can only remit payment to a currently-valid bank account.",
                        "group": [
                            "B"
                        ],
                        "schema": [
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints": {
                            "fields": [
                                {
                                    "path": [
                                        "$.issuer.id",
                                        "$.vc.issuer.id"
                                    ],
                                    "purpose": "We can only verify bank accounts if they are attested by a trusted bank, auditor or regulatory authority.",
                                    "filter": {
                                        "type": "string",
                                        "pattern": "did:example:489398593"
                                    }
                                },
                                {
                                    "path": [
                                        "$.credentialSubject.account[*].route",
                                        "$.vc.credentialSubject.account[*].route",
                                        "$.account[*].route"
                                    ],
                                    "purpose": "We can only remit payment to a currently-valid account at a US, Japanese, or German federally-accredited bank, submitted as an ABA RTN or SWIFT code.",
                                    "filter": {
                                        "type": "string",
                                        "pattern": "^[0-9]{9}|^([a-zA-Z]){4}([a-zA-Z]){2}([0-9a-zA-Z]){2}([0-9a-zA-Z]{3})?$"
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        with pytest.raises(DIFPresExchError):
            test_pd = PresentationDefinition.deserialize(test_json_pd)
            await dif_pres_exch_handler.make_requirement(
                srs=test_pd.submission_requirements,
                descriptors=test_pd.input_descriptors,
            )

        test_json_pd_nested_srs = """
            {
                "submission_requirements": [
                    {
                        "name": "Citizenship Information",
                        "rule": "pick",
                        "max": 3,
                        "from_nested": [
                            {
                                "name": "United States Citizenship Proofs",
                                "purpose": "We need you to prove your US citizenship.",
                                "rule": "all",
                                "from": "C"
                            },
                            {
                                "name": "European Union Citizenship Proofs",
                                "purpose": "We need you to prove you are a citizen of an EU member state.",
                                "rule": "all",
                                "from": "D"
                            }
                        ]
                    }
                ],
                "id": "32f54163-7166-48f1-93d8-ff217bdb0653",
                "input_descriptors": [
                    {
                        "id": "banking_input_1",
                        "name": "Bank Account Information",
                        "purpose": "We can only remit payment to a currently-valid bank account.",
                        "group": [
                            "B"
                        ],
                        "schema": [
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints": {
                            "fields": [
                                {
                                    "path": [
                                        "$.issuer.id",
                                        "$.vc.issuer.id"
                                    ],
                                    "purpose": "We can only verify bank accounts if they are attested by a trusted bank, auditor or regulatory authority.",
                                    "filter": {
                                        "type": "string",
                                        "pattern": "did:example:489398593"
                                    }
                                },
                                {
                                    "path": [
                                        "$.credentialSubject.account[*].route",
                                        "$.vc.credentialSubject.account[*].route",
                                        "$.account[*].route"
                                    ],
                                    "purpose": "We can only remit payment to a currently-valid account at a US, Japanese, or German federally-accredited bank, submitted as an ABA RTN or SWIFT code.",
                                    "filter": {
                                        "type": "string",
                                        "pattern": "^[0-9]{9}|^([a-zA-Z]){4}([a-zA-Z]){2}([0-9a-zA-Z]){2}([0-9a-zA-Z]{3})?$"
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        with pytest.raises(DIFPresExchError):
            test_pd = PresentationDefinition.deserialize(test_json_pd_nested_srs)
            await dif_pres_exch_handler.make_requirement(
                srs=test_pd.submission_requirements,
                descriptors=test_pd.input_descriptors,
            )

    @pytest.mark.asyncio
    async def test_make_requirement_with_none_params(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_json_pd_no_sr = """
            {
                "id": "32f54163-7166-48f1-93d8-ff217bdb0653",
                "input_descriptors": [
                    {
                        "id": "banking_input_1",
                        "name": "Bank Account Information",
                        "purpose": "We can only remit payment to a currently-valid bank account.",
                        "group": [
                            "B"
                        ],
                        "schema": [
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints": {
                            "fields": [
                                {
                                    "path": [
                                        "$.issuer.id",
                                        "$.vc.issuer.id"
                                    ],
                                    "purpose": "We can only verify bank accounts if they are attested by a trusted bank, auditor or regulatory authority.",
                                    "filter": {
                                        "type": "string",
                                        "pattern": "did:example:489398593"
                                    }
                                },
                                {
                                    "path": [
                                        "$.credentialSubject.account[*].route",
                                        "$.vc.credentialSubject.account[*].route",
                                        "$.account[*].route"
                                    ],
                                    "purpose": "We can only remit payment to a currently-valid account at a US, Japanese, or German federally-accredited bank, submitted as an ABA RTN or SWIFT code.",
                                    "filter": {
                                        "type": "string",
                                        "pattern": "^[0-9]{9}|^([a-zA-Z]){4}([a-zA-Z]){2}([0-9a-zA-Z]){2}([0-9a-zA-Z]{3})?$"
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        test_pd = PresentationDefinition.deserialize(test_json_pd_no_sr)
        assert test_pd.submission_requirements is None
        await dif_pres_exch_handler.make_requirement(
            srs=test_pd.submission_requirements, descriptors=test_pd.input_descriptors
        )

        test_json_pd_no_input_desc = """
            {
                "submission_requirements": [
                    {
                        "name": "Banking Information",
                        "purpose": "We need you to prove you currently hold a bank account older than 12months.",
                        "rule": "pick",
                        "count": 1,
                        "from": "A"
                    }
                ],
                "id": "32f54163-7166-48f1-93d8-ff217bdb0653"
            }
        """

        with pytest.raises(DIFPresExchError):
            test_pd = PresentationDefinition.deserialize(test_json_pd_no_input_desc)
            await dif_pres_exch_handler.make_requirement(
                srs=test_pd.submission_requirements,
                descriptors=test_pd.input_descriptors,
            )

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_subject_is_issuer_check(self, setup_tuple, profile):
        cred_list, pd_list = setup_tuple
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_pd = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                    "name": "Citizenship Information",
                    "rule": "pick",
                    "min": 1,
                    "from": "A"
                    },
                    {
                    "name": "European Union Citizenship Proofs",
                    "rule": "all",
                    "from": "B"
                    }
                ],
                "input_descriptors":[
                    {
                        "id":"citizenship_input_1",
                        "name":"EU Driver's License",
                        "group":[
                            "A"
                        ],
                        "schema":[
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints":{
                            "subject_is_issuer": "required",
                            "fields":[
                                {
                                    "path":[
                                        "$.issuer.id",
                                        "$.vc.issuer.id"
                                    ],
                                    "purpose":"The claim must be from one of the specified issuers",
                                    "filter":{
                                        "type":"string",
                                        "enum": ["did:key:zUC72Q7XD4PE4CrMiDVXuvZng3sBvMmaGgNeTUJuzavH2BS7ThbHL9FhsZM9QYY5fqAQ4MB8M9oudz3tfuaX36Ajr97QRW7LBt6WWmrtESe6Bs5NYzFtLWEmeVtvRYVAgjFcJSa", "did:example:489398593", "did:sov:2wJPyULfLLnYTEFYzByfUR"]
                                    }
                                }
                            ]
                        }
                    },
                    {
                        "id":"citizenship_input_2",
                        "name":"US Passport",
                        "group":[
                            "B"
                        ],
                        "schema":[
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints":{
                            "fields":[
                                {
                                    "path":[
                                        "$.issuanceDate",
                                        "$.vc.issuanceDate"
                                    ],
                                    "filter":{
                                        "type":"string",
                                        "format":"date",
                                        "minimum":"2009-5-16"
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=cred_list,
            pd=PresentationDefinition.deserialize(test_pd),
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_limit_disclosure_required_check(self, setup_tuple, profile):
        cred_list, pd_list = setup_tuple
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_pd = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                    "name": "Citizenship Information",
                    "rule": "pick",
                    "min": 1,
                    "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                        "id":"citizenship_input_1",
                        "name":"EU Driver's License",
                        "group":[
                            "A"
                        ],
                        "schema":[
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints":{
                            "limit_disclosure": "required",
                            "fields":[
                                {
                                    "path":[
                                        "$.credentialSubject.givenName"
                                    ],
                                    "purpose":"The claim must be from one of the specified issuers",
                                    "filter":{
                                        "type":"string",
                                        "enum": ["JOHN", "CAI"]
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd)
        assert tmp_pd.input_descriptors[0].constraint.limit_disclosure
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=cred_list,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 1
        for cred in tmp_vp.get("verifiableCredential"):
            assert cred["issuer"] in [
                "did:key:zUC72Q7XD4PE4CrMiDVXuvZng3sBvMmaGgNeTUJuzavH2BS7ThbHL9FhsZM9QYY5fqAQ4MB8M9oudz3tfuaX36Ajr97QRW7LBt6WWmrtESe6Bs5NYzFtLWEmeVtvRYVAgjFcJSa",
                "did:example:489398593",
                "did:sov:2wJPyULfLLnYTEFYzByfUR",
            ]
            assert cred["proof"]["type"] == "BbsBlsSignatureProof2020"

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_reveal_doc_a(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_constraint = {
            "limit_disclosure": "required",
            "fields": [
                {
                    "path": ["$.credentialSubject.givenName"],
                    "filter": {"type": "string", "const": "JOHN"},
                },
                {
                    "path": ["$.credentialSubject.familyName"],
                    "filter": {"type": "string", "const": "SMITH"},
                },
                {
                    "path": ["$.credentialSubject.type"],
                    "filter": {
                        "type": "string",
                        "enum": ["PermanentResident", "Person"],
                    },
                },
                {
                    "path": ["$.credentialSubject.gender"],
                    "filter": {"type": "string", "const": "Male"},
                },
            ],
        }

        test_constraint = Constraints.deserialize(test_constraint)
        tmp_reveal_doc = dif_pres_exch_handler.reveal_doc(
            credential_dict=BBS_SIGNED_VC_MATTR, constraints=test_constraint
        )
        assert tmp_reveal_doc

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_reveal_doc_b(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_credential = {
            "@context": [
                "https://www.w3.org/2018/credentials/v1",
                "https://www.w3.org/2018/credentials/examples/v1",
                "https://w3id.org/security/bbs/v1",
            ],
            "id": "https://example.gov/credentials/3732",
            "issuer": "did:example:489398593",
            "type": ["VerifiableCredential", "UniversityDegreeCredential"],
            "issuanceDate": "2020-03-10T04:24:12.164Z",
            "credentialSubject": {
                "id": "did:example:b34ca6cd37bbf23",
                "degree": {
                    "type": "BachelorDegree",
                    "name": "Bachelor of Science and Arts",
                    "degreeType": "Underwater Basket Weaving",
                },
                "college": "Contoso University",
            },
            "proof": {
                "type": "BbsBlsSignature2020",
                "verificationMethod": "did:key:zUC72Q7XD4PE4CrMiDVXuvZng3sBvMmaGgNeTUJuzavH2BS7ThbHL9FhsZM9QYY5fqAQ4MB8M9oudz3tfuaX36Ajr97QRW7LBt6WWmrtESe6Bs5NYzFtLWEmeVtvRYVAgjFcJSa#zUC72Q7XD4PE4CrMiDVXuvZng3sBvMmaGgNeTUJuzavH2BS7ThbHL9FhsZM9QYY5fqAQ4MB8M9oudz3tfuaX36Ajr97QRW7LBt6WWmrtESe6Bs5NYzFtLWEmeVtvRYVAgjFcJSa",
                "created": "2021-04-14T15:56:26.427788",
                "proofPurpose": "assertionMethod",
                "proofValue": "q86pBug3pGMMXq0RE6jfQnk8HaIfM4lb9dQAnKM4aUkT64x/f/65tfnzooeVPf+vXR9a2TVParet6RKWVHVb1QB+GJMWglBy29iEz2tK8H8qYqLtRHMA3YCAQ/aynHKekSsURq+1c2RTEsX27G0hVA==",
            },
        }

        test_constraint = {
            "limit_disclosure": "required",
            "fields": [
                {
                    "path": ["$.credentialSubject.degree.name"],
                    "filter": {
                        "type": "string",
                        "const": "Bachelor of Science and Arts",
                    },
                },
                {
                    "path": ["$.issuer"],
                    "filter": {
                        "type": "string",
                        "const": "did:example:489398593",
                    },
                },
                {
                    "path": ["$.issuanceDate"],
                    "filter": {
                        "type": "string",
                        "const": "2020-03-10T04:24:12.164Z",
                    },
                },
            ],
        }
        test_constraint = Constraints.deserialize(test_constraint)
        tmp_reveal_doc = dif_pres_exch_handler.reveal_doc(
            credential_dict=test_credential, constraints=test_constraint
        )
        assert tmp_reveal_doc == BBS_NESTED_VC_REVEAL_DOCUMENT_MATTR

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_reveal_doc_c(self, setup_tuple, profile):
        cred_list, pd_list = setup_tuple
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_constraint = {
            "limit_disclosure": "required",
            "fields": [
                {
                    "path": ["$.credentialSubject.givenName"],
                    "filter": {"type": "string", "const": "Cai"},
                },
                {
                    "path": ["$.credentialSubject.familyName"],
                    "filter": {"type": "string", "const": "Leblanc"},
                },
                {
                    "path": ["$.credentialSubject.gender"],
                    "filter": {"type": "string", "const": "Male"},
                },
            ],
        }

        test_constraint = Constraints.deserialize(test_constraint)
        test_cred = cred_list[2].cred_value
        tmp_reveal_doc = dif_pres_exch_handler.reveal_doc(
            credential_dict=test_cred, constraints=test_constraint
        )
        assert tmp_reveal_doc

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_filter_number_type_check(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_pd_min = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "pick",
                        "min": 1,
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                    "id":"citizenship_input_1",
                    "name":"EU Driver's License",
                    "group":[
                        "A"
                    ],
                    "schema":[
                        {
                            "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                        }
                    ],
                    "constraints":{
                        "fields":[
                            {
                                "path":[
                                    "$.credentialSubject.test",
                                    "$.vc.credentialSubject.test",
                                    "$.test"
                                ],
                                "purpose":"The claim must be from one of the specified issuers",
                                "filter":{  
                                    "type": "number",
                                    "maximum": 2
                                }
                            }
                        ]
                    }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_min)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=bbs_bls_number_filter_creds,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 2
        test_pd_max = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "pick",
                        "min": 1,
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                    "id":"citizenship_input_1",
                    "name":"EU Driver's License",
                    "group":[
                        "A"
                    ],
                    "schema":[
                        {
                            "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                        }
                    ],
                    "constraints":{
                        "fields":[
                            {
                                "path":[
                                    "$.credentialSubject.test",
                                    "$.vc.credentialSubject.test",
                                    "$.test"
                                ],
                                "purpose":"The claim must be from one of the specified issuers",
                                "filter":{  
                                    "type": "number",
                                    "minimum": 2
                                }
                            }
                        ]
                    }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_max)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=bbs_bls_number_filter_creds,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 3

        test_pd_excl_min = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "pick",
                        "min": 1,
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                    "id":"citizenship_input_1",
                    "name":"EU Driver's License",
                    "group":[
                        "A"
                    ],
                    "schema":[
                        {
                            "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                        }
                    ],
                    "constraints":{
                        "limit_disclosure": "preferred",
                        "fields":[
                            {
                                "path":[
                                    "$.credentialSubject.test",
                                    "$.vc.credentialSubject.test",
                                    "$.test"
                                ],
                                "purpose":"The claim must be from one of the specified issuers",
                                "filter":{  
                                    "type": "number",
                                    "exclusiveMinimum": 1.5
                                }
                            }
                        ]
                    }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_excl_min)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=bbs_bls_number_filter_creds,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 3

        test_pd_excl_max = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "pick",
                        "min": 1,
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                    "id":"citizenship_input_1",
                    "name":"EU Driver's License",
                    "group":[
                        "A"
                    ],
                    "schema":[
                        {
                            "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                        }
                    ],
                    "constraints":{
                        "fields":[
                            {
                                "path":[
                                    "$.credentialSubject.test",
                                    "$.vc.credentialSubject.test",
                                    "$.test"
                                ],
                                "purpose":"The claim must be from one of the specified issuers",
                                "filter":{  
                                    "type": "number",
                                    "exclusiveMaximum": 2.5
                                }
                            }
                        ]
                    }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_excl_max)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=bbs_bls_number_filter_creds,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 2

        test_pd_const = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "pick",
                        "min": 1,
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                    "id":"citizenship_input_1",
                    "name":"EU Driver's License",
                    "group":[
                        "A"
                    ],
                    "schema":[
                        {
                            "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                        }
                    ],
                    "constraints":{
                        "fields":[
                            {
                                "path":[
                                    "$.credentialSubject.test",
                                    "$.vc.credentialSubject.test",
                                    "$.test"
                                ],
                                "purpose":"The claim must be from one of the specified issuers",
                                "filter":{  
                                    "type": "number",
                                    "const": 2
                                }
                            }
                        ]
                    }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_const)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=bbs_bls_number_filter_creds,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 2

        test_pd_enum = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "pick",
                        "min": 1,
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                    "id":"citizenship_input_1",
                    "name":"EU Driver's License",
                    "group":[
                        "A"
                    ],
                    "schema":[
                        {
                            "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                        }
                    ],
                    "constraints":{
                        "fields":[
                            {
                                "path":[
                                    "$.credentialSubject.test",
                                    "$.vc.credentialSubject.test",
                                    "$.test"
                                ],
                                "purpose":"The claim must be from one of the specified issuers",
                                "filter":{  
                                    "type": "number",
                                    "enum": [2, 2.0 , "test"]
                                }
                            }
                        ]
                    }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_enum)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=bbs_bls_number_filter_creds,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 2

        test_pd_missing = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "pick",
                        "min": 1,
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                    "id":"citizenship_input_1",
                    "name":"EU Driver's License",
                    "group":[
                        "A"
                    ],
                    "schema":[
                        {
                            "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                        }
                    ],
                    "constraints":{
                        "fields":[
                            {
                                "path":[
                                    "$.credentialSubject.test",
                                    "$.vc.credentialSubject.test",
                                    "$.test"
                                ],
                                "purpose":"The claim must be from one of the specified issuers",
                                "filter":{  
                                    "type": "number",
                                    "enum": [2.5]
                                }
                            }
                        ]
                    }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_missing)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=bbs_bls_number_filter_creds,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 0

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_filter_no_type_check(self, setup_tuple, profile):
        cred_list, pd_list = setup_tuple
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_pd = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "all",
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                    "id":"citizenship_input_1",
                    "name":"EU Driver's License",
                    "group":[
                        "A"
                    ],
                    "schema":[
                        {
                            "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                        }
                    ],
                    "constraints":{
                        "fields":[
                            {
                                "path":[
                                    "$.credentialSubject.lprCategory",
                                    "$.vc.credentialSubject.lprCategory",
                                    "$.test"
                                ],
                                "purpose":"The claim must be from one of the specified issuers",
                                "filter":{  
                                    "not": {
                                        "const": "C10"
                                    }
                                }
                            }
                        ]
                    }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=cred_list,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 6

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_edd_limit_disclosure(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_pd = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                    "name": "Citizenship Information",
                    "rule": "pick",
                    "min": 1,
                    "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                        "id":"citizenship_input_1",
                        "name":"EU Driver's License",
                        "group":[
                            "A"
                        ],
                        "schema":[
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints":{
                            "limit_disclosure": "required",
                            "fields":[
                                {
                                    "path":[
                                        "$.issuer.id",
                                        "$.issuer",
                                        "$.vc.issuer.id"
                                    ],
                                    "purpose":"The claim must be from one of the specified issuers",
                                    "filter":{
                                        "enum": ["did:key:zUC72Q7XD4PE4CrMiDVXuvZng3sBvMmaGgNeTUJuzavH2BS7ThbHL9FhsZM9QYY5fqAQ4MB8M9oudz3tfuaX36Ajr97QRW7LBt6WWmrtESe6Bs5NYzFtLWEmeVtvRYVAgjFcJSa", "did:example:489398593"]
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd)
        assert tmp_pd.input_descriptors[0].constraint.limit_disclosure
        with pytest.raises(LinkedDataProofException):
            await dif_pres_exch_handler.create_vp(
                credentials=edd_jsonld_creds,
                pd=tmp_pd,
                challenge="1f44d55f-f161-4938-a659-f8026467f126",
            )

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_edd_jsonld_creds(self, setup_tuple, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_pd_const_check = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "all",
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                        "id":"citizenship_input_1",
                        "name":"EU Driver's License",
                        "group":[
                            "A"
                        ],
                        "schema":[
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints":{
                            "fields":[
                                {
                                    "path":[
                                        "$.vc.issuer.id",
                                        "$.issuer",
                                        "$.issuer.id"
                                    ],
                                    "filter":{
                                        "type":"string",
                                        "const": "did:example:489398593"
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_const_check)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=edd_jsonld_creds,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 3

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_filter_string(self, setup_tuple, profile):
        cred_list, pd_list = setup_tuple
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_pd_min_length = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "all",
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                        "id":"citizenship_input_1",
                        "name":"EU Driver's License",
                        "group":[
                            "A"
                        ],
                        "schema":[
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints":{
                            "fields":[
                                {
                                    "path":[
                                        "$.vc.issuer.id",
                                        "$.issuer",
                                        "$.issuer.id"
                                    ],
                                    "filter":{
                                        "type":"string",
                                        "minLength": 5
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_min_length)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=cred_list,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 6

        test_pd_max_length = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "all",
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                        "id":"citizenship_input_1",
                        "name":"EU Driver's License",
                        "group":[
                            "A"
                        ],
                        "schema":[
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints":{
                            "fields":[
                                {
                                    "path":[
                                        "$.issuer.id",
                                        "$.issuer",
                                        "$.vc.issuer.id"
                                    ],
                                    "filter":{
                                        "type":"string",
                                        "maxLength": 150
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_max_length)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=cred_list,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 6

        test_pd_pattern_check = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "all",
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                        "id":"citizenship_input_1",
                        "name":"EU Driver's License",
                        "group":[
                            "A"
                        ],
                        "schema":[
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints":{
                            "fields":[
                                {
                                    "path":[
                                        "$.vc.issuer.id",
                                        "$.issuer",
                                        "$.issuer.id"
                                    ],
                                    "filter":{
                                        "type":"string",
                                        "pattern": "did:example:test"
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_pattern_check)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=cred_list,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 0

        test_pd_datetime_exclmax = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "all",
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                        "id":"citizenship_input_1",
                        "name":"EU Driver's License",
                        "group":[
                            "A"
                        ],
                        "schema":[
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints":{
                            "fields":[
                                {
                                    "path":[
                                        "$.issuanceDate",
                                        "$.vc.issuanceDate"
                                    ],
                                    "filter":{
                                        "type":"string",
                                        "format":"date",
                                        "exclusiveMaximum":"2011-5-16"
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_datetime_exclmax)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=cred_list,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 6

        test_pd_datetime_exclmin = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "all",
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                        "id":"citizenship_input_1",
                        "name":"EU Driver's License",
                        "group":[
                            "A"
                        ],
                        "schema":[
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints":{
                            "fields":[
                                {
                                    "path":[
                                        "$.issuanceDate",
                                        "$.vc.issuanceDate"
                                    ],
                                    "filter":{
                                        "type":"string",
                                        "format":"date",
                                        "exclusiveMinimum":"2008-5-16"
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_datetime_exclmin)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=cred_list,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 6

        test_pd_const_check = """
            {
                "id":"32f54163-7166-48f1-93d8-ff217bdb0653",
                "submission_requirements":[
                    {
                        "name": "European Union Citizenship Proofs",
                        "rule": "all",
                        "from": "A"
                    }
                ],
                "input_descriptors":[
                    {
                        "id":"citizenship_input_1",
                        "name":"EU Driver's License",
                        "group":[
                            "A"
                        ],
                        "schema":[
                            {
                                "uri":"https://www.w3.org/2018/credentials#VerifiableCredential"
                            }
                        ],
                        "constraints":{
                            "fields":[
                                {
                                    "path":[
                                        "$.vc.issuer.id",
                                        "$.issuer",
                                        "$.issuer.id"
                                    ],
                                    "filter":{
                                        "type":"string",
                                        "const": "did:example:489398593"
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        """

        tmp_pd = PresentationDefinition.deserialize(test_pd_const_check)
        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=cred_list,
            pd=tmp_pd,
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 1

    @pytest.mark.asyncio
    async def test_filter_schema(self, setup_tuple, profile):
        cred_list, pd_list = setup_tuple
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        tmp_schema_list = [
            SchemaInputDescriptor(
                uri="test123",
                required=True,
            )
        ]
        assert (
            len(await dif_pres_exch_handler.filter_schema(cred_list, tmp_schema_list))
            == 0
        )

    @pytest.mark.asyncio
    async def test_cred_schema_match(self, setup_tuple, profile):
        cred_list, pd_list = setup_tuple
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        tmp_cred = deepcopy(cred_list[0])
        assert (
            await dif_pres_exch_handler.credential_match_schema(
                tmp_cred, "https://www.w3.org/2018/credentials#VerifiableCredential"
            )
            is True
        )

    @pytest.mark.asyncio
    async def test_merge_nested(self, setup_tuple, profile):
        cred_list, pd_list = setup_tuple
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_nested_result = []
        test_dict_1 = {}
        test_dict_1["citizenship_input_1"] = [
            cred_list[0],
            cred_list[1],
            cred_list[2],
            cred_list[3],
            cred_list[4],
            cred_list[5],
        ]
        test_dict_2 = {}
        test_dict_2["citizenship_input_2"] = [
            cred_list[4],
            cred_list[5],
        ]
        test_dict_3 = {}
        test_dict_3["citizenship_input_2"] = [
            cred_list[3],
            cred_list[2],
        ]
        test_nested_result.append(test_dict_1)
        test_nested_result.append(test_dict_2)
        test_nested_result.append(test_dict_3)

        tmp_result = await dif_pres_exch_handler.merge_nested_results(
            test_nested_result, {}
        )

    @pytest.mark.asyncio
    async def test_subject_is_issuer(self, setup_tuple, profile):
        cred_list, pd_list = setup_tuple
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        tmp_cred = deepcopy(cred_list[0])
        tmp_cred.issuer_id = "4fc82e63-f897-4dad-99cc-f698dff6c425"
        tmp_cred.subject_ids.add("4fc82e63-f897-4dad-99cc-f698dff6c425")
        assert tmp_cred.subject_ids is not None
        assert await dif_pres_exch_handler.subject_is_issuer(tmp_cred) is True
        tmp_cred.issuer_id = "19b823fb-55ef-49f4-8caf-2a26b8b9286f"
        assert await dif_pres_exch_handler.subject_is_issuer(tmp_cred) is False

    @pytest.mark.asyncio
    def test_is_numeric(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        assert dif_pres_exch_handler.is_numeric("test") is False
        assert dif_pres_exch_handler.is_numeric(1) is True
        assert dif_pres_exch_handler.is_numeric(2 + 3j) is False

    @pytest.mark.asyncio
    def test_filter_no_match(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        tmp_filter_excl_min = Filter(exclusive_min=7)
        assert (
            dif_pres_exch_handler.exclusive_minimum_check("test", tmp_filter_excl_min)
            is False
        )
        tmp_filter_excl_max = Filter(exclusive_max=10)
        assert (
            dif_pres_exch_handler.exclusive_maximum_check("test", tmp_filter_excl_max)
            is False
        )
        tmp_filter_min = Filter(minimum=10)
        assert dif_pres_exch_handler.minimum_check("test", tmp_filter_min) is False
        tmp_filter_max = Filter(maximum=10)
        assert dif_pres_exch_handler.maximum_check("test", tmp_filter_max) is False

    @pytest.mark.asyncio
    def test_filter_valueerror(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        tmp_filter_excl_min = Filter(exclusive_min=7, fmt="date")
        assert (
            dif_pres_exch_handler.exclusive_minimum_check("test", tmp_filter_excl_min)
            is False
        )
        tmp_filter_excl_max = Filter(exclusive_max=10, fmt="date")
        assert (
            dif_pres_exch_handler.exclusive_maximum_check("test", tmp_filter_excl_max)
            is False
        )
        tmp_filter_min = Filter(minimum=10, fmt="date")
        assert dif_pres_exch_handler.minimum_check("test", tmp_filter_min) is False
        tmp_filter_max = Filter(maximum=10, fmt="date")
        assert dif_pres_exch_handler.maximum_check("test", tmp_filter_max) is False

    @pytest.mark.asyncio
    def test_filter_length_check(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        tmp_filter_both = Filter(min_length=7, max_length=10)
        assert dif_pres_exch_handler.length_check("test12345", tmp_filter_both) is True
        tmp_filter_min = Filter(min_length=7)
        assert dif_pres_exch_handler.length_check("test123", tmp_filter_min) is True
        tmp_filter_max = Filter(max_length=10)
        assert dif_pres_exch_handler.length_check("test", tmp_filter_max) is True
        assert dif_pres_exch_handler.length_check("test12", tmp_filter_min) is False

    @pytest.mark.asyncio
    def test_filter_pattern_check(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        tmp_filter = Filter(pattern="test1|test2")
        assert dif_pres_exch_handler.pattern_check("test3", tmp_filter) is False
        tmp_filter = Filter(const="test3")
        assert dif_pres_exch_handler.pattern_check("test3", tmp_filter) is False

    @pytest.mark.asyncio
    def test_is_len_applicable(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        tmp_req_a = Requirement(count=1)
        tmp_req_b = Requirement(minimum=3)
        tmp_req_c = Requirement(maximum=5)

        assert dif_pres_exch_handler.is_len_applicable(tmp_req_a, 2) is False
        assert dif_pres_exch_handler.is_len_applicable(tmp_req_b, 2) is False
        assert dif_pres_exch_handler.is_len_applicable(tmp_req_c, 6) is False

    @pytest.mark.asyncio
    def test_create_vcrecord(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_cred_dict = {
            "@context": [
                "https://www.w3.org/2018/credentials/v1",
                "https://www.w3.org/2018/credentials/examples/v1",
            ],
            "id": "http://example.edu/credentials/3732",
            "type": ["VerifiableCredential", "UniversityDegreeCredential"],
            "issuer": {"id": "https://example.edu/issuers/14"},
            "issuanceDate": "2010-01-01T19:23:24Z",
            "credentialSubject": {
                "id": "did:example:b34ca6cd37bbf23",
                "degree": {
                    "type": "BachelorDegree",
                    "name": "Bachelor of Science and Arts",
                },
            },
            "credentialSchema": {
                "id": "https://example.org/examples/degree.json",
                "type": "JsonSchemaValidator2018",
            },
        }
        test_vcrecord = dif_pres_exch_handler.create_vcrecord(test_cred_dict)
        assert isinstance(test_vcrecord, VCRecord)

    @pytest.mark.asyncio
    async def test_reveal_doc_d(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(
            profile, pres_signing_did="did:example:b34ca6cd37bbf23"
        )
        test_constraint = {
            "limit_disclosure": "required",
            "fields": [
                {
                    "path": ["$.credentialSubject.accounts[*].accountnumber"],
                    "filter": {"type": "string", "const": "test"},
                }
            ],
        }
        test_cred_dict = {
            "@context": [
                "https://www.w3.org/2018/credentials/v1",
                "https://w3id.org/citizenship/v1",
                "https://w3id.org/security/bbs/v1",
            ],
            "id": "https://issuer.oidp.uscis.gov/credentials/83627465",
            "type": ["VerifiableCredential", "PermanentResidentCard"],
            "issuer": "did:example:489398593",
            "identifier": "83627465",
            "name": "Permanent Resident Card",
            "description": "Government of Example Permanent Resident Card.",
            "issuanceDate": "2019-12-03T12:19:52Z",
            "expirationDate": "2029-12-03T12:19:52Z",
            "credentialSubject": {
                "id": "did:example:b34ca6cd37bbf23",
                "accounts": [
                    {"accountnumber": "test"},
                    {"accountnumber": "test"},
                    {"accountnumber": "test"},
                ],
            },
            "proof": {
                "type": "BbsBlsSignature2020",
                "created": "2020-10-16T23:59:31Z",
                "proofPurpose": "assertionMethod",
                "proofValue": "kAkloZSlK79ARnlx54tPqmQyy6G7/36xU/LZgrdVmCqqI9M0muKLxkaHNsgVDBBvYp85VT3uouLFSXPMr7Stjgq62+OCunba7bNdGfhM/FUsx9zpfRtw7jeE182CN1cZakOoSVsQz61c16zQikXM3w==",
                "verificationMethod": "did:example:489398593#test",
            },
        }
        test_constraint = Constraints.deserialize(test_constraint)
        tmp_reveal_doc = dif_pres_exch_handler.reveal_doc(
            credential_dict=test_cred_dict, constraints=test_constraint
        )
        assert tmp_reveal_doc

    @pytest.mark.asyncio
    async def test_credential_subject_as_list(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        with async_mock.patch.object(
            dif_pres_exch_handler, "new_credential_builder", autospec=True
        ) as mock_cred_builder:
            mock_cred_builder.return_value = {}
            dif_pres_exch_handler.reveal_doc(
                {"credentialSubject": []}, Constraints(_fields=[])
            )

    def test_invalid_number_filter(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        assert not dif_pres_exch_handler.process_numeric_val(val=2, _filter=Filter())

    def test_invalid_string_filter(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        assert not dif_pres_exch_handler.process_string_val(
            val="test", _filter=Filter()
        )

    @pytest.mark.asyncio
    async def test_credential_schema_match(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_cred_dict = {
            "@context": [
                "https://www.w3.org/2018/credentials/v1",
                "https://www.w3.org/2018/credentials/examples/v1",
            ],
            "id": "http://example.edu/credentials/3732",
            "type": ["VerifiableCredential", "UniversityDegreeCredential"],
            "issuer": {"id": "https://example.edu/issuers/14"},
            "issuanceDate": "2010-01-01T19:23:24Z",
            "credentialSubject": {
                "id": "did:example:b34ca6cd37bbf23",
                "degree": {
                    "type": "BachelorDegree",
                    "name": "Bachelor of Science and Arts",
                },
            },
            "credentialSchema": {
                "id": "https://example.org/examples/degree.json",
                "type": "JsonSchemaValidator2018",
            },
        }
        test_cred = dif_pres_exch_handler.create_vcrecord(test_cred_dict)
        assert await dif_pres_exch_handler.credential_match_schema(
            test_cred, "https://example.org/examples/degree.json"
        )

    def test_verification_method(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        assert (
            dif_pres_exch_handler._get_verification_method(
                "did:key:z6Mkgg342Ycpuk263R9d8Aq6MUaxPn1DDeHyGo38EefXmgDL"
            )
            == DIDKey.from_did(
                "did:key:z6Mkgg342Ycpuk263R9d8Aq6MUaxPn1DDeHyGo38EefXmgDL"
            ).key_id
        )
        with pytest.raises(DIFPresExchError):
            dif_pres_exch_handler._get_verification_method("did:test:test")

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_sign_pres_no_cred_subject_id(self, profile, setup_tuple):
        dif_pres_exch_handler = DIFPresExchHandler(
            profile, pres_signing_did="did:sov:WgWxqztrNooG92RXvxSTWv"
        )
        cred_list, pd_list = setup_tuple
        tmp_pd = pd_list[3]
        tmp_creds = []
        for cred in deepcopy(cred_list):
            cred.subject_ids = []
            tmp_creds.append(cred)

        tmp_vp = await dif_pres_exch_handler.create_vp(
            credentials=tmp_creds,
            pd=tmp_pd[0],
            challenge="1f44d55f-f161-4938-a659-f8026467f126",
        )
        assert len(tmp_vp.get("verifiableCredential")) == 6

    @pytest.mark.asyncio
    @pytest.mark.ursa_bbs_signatures
    async def test_sign_pres_no_cred_subject_id_error(self, profile, setup_tuple):
        dif_pres_exch_handler = DIFPresExchHandler(
            profile, pres_signing_did="did:sov:WgWxqztrNooG92RXvxSTWv"
        )
        cred_list, pd_list = setup_tuple
        tmp_pd = pd_list[3]
        tmp_creds = []
        for cred in deepcopy(cred_list):
            cred.subject_ids = []
            cred.proof_types = [BbsBlsSignatureProof2020.signature_type]
            tmp_creds.append(cred)
        with pytest.raises(DIFPresExchError):
            tmp_vp = await dif_pres_exch_handler.create_vp(
                credentials=tmp_creds,
                pd=tmp_pd[0],
                challenge="1f44d55f-f161-4938-a659-f8026467f126",
            )

    def test_get_sign_key_credential_subject_id(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        VC_RECORDS_A = [
            VCRecord(
                contexts=[
                    "https://www.w3.org/2018/credentials/v1",
                    "https://www.w3.org/2018/credentials/v1/examples",
                ],
                types=[
                    "VerifiableCredential",
                    "AlumniCredential",
                ],
                issuer_id="https://example.edu/issuers/565049",
                subject_ids=["did:example:ebfeb1f712ebc6f1c276e12ec21"],
                proof_types=["Ed25519Signature2018"],
                schema_ids=["https://example.org/examples/degree.json"],
                cred_value={"...": "..."},
                given_id="http://example.edu/credentials/3732",
                cred_tags={"some": "tag"},
            ),
            VCRecord(
                contexts=[
                    "https://www.w3.org/2018/credentials/v1",
                    "https://www.w3.org/2018/credentials/v1/examples",
                ],
                types=[
                    "VerifiableCredential",
                    "AlumniCredential",
                ],
                issuer_id="https://example.edu/issuers/565049",
                subject_ids=["did:example:ebfeb1f712ebc6f1c276e12ec31"],
                proof_types=["Ed25519Signature2018"],
                schema_ids=["https://example.org/examples/degree.json"],
                cred_value={"...": "..."},
                given_id="http://example.edu/credentials/3732",
                cred_tags={"some": "tag"},
            ),
        ]
        with pytest.raises(DIFPresExchError):
            dif_pres_exch_handler.get_sign_key_credential_subject_id(VC_RECORDS_A)

        VC_RECORDS_B = [
            VCRecord(
                contexts=[
                    "https://www.w3.org/2018/credentials/v1",
                    "https://www.w3.org/2018/credentials/v1/examples",
                ],
                types=[
                    "VerifiableCredential",
                    "AlumniCredential",
                ],
                issuer_id="https://example.edu/issuers/565049",
                subject_ids=["did:example:ebfeb1f712ebc6f1c276e12ec21"],
                proof_types=["Ed25519Signature2018"],
                schema_ids=["https://example.org/examples/degree.json"],
                cred_value={"...": "..."},
                given_id="http://example.edu/credentials/3732",
                cred_tags={"some": "tag"},
            ),
            VCRecord(
                contexts=[
                    "https://www.w3.org/2018/credentials/v1",
                    "https://www.w3.org/2018/credentials/v1/examples",
                ],
                types=[
                    "VerifiableCredential",
                    "AlumniCredential",
                ],
                issuer_id="https://example.edu/issuers/565049",
                subject_ids=[
                    "did:example:ebfeb1f712ebc6f1c276e12ec31",
                    "did:example:ebfeb1f712ebc6f1c276e12ec21",
                ],
                proof_types=["Ed25519Signature2018"],
                schema_ids=["https://example.org/examples/degree.json"],
                cred_value={"...": "..."},
                given_id="http://example.edu/credentials/3732",
                cred_tags={"some": "tag"},
            ),
        ]
        dif_pres_exch_handler.get_sign_key_credential_subject_id(VC_RECORDS_B)

    @pytest.mark.asyncio
    async def test_filter_constraint_no_derive_key(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_cred = {
            "@context": [
                "https://www.w3.org/2018/credentials/v1",
                "https://w3id.org/citizenship/v1",
                "https://w3id.org/security/bbs/v1",
            ],
            "id": "https://issuer.oidp.uscis.gov/credentials/83627465",
            "type": ["VerifiableCredential", "PermanentResidentCard"],
            "issuer": "did:example:489398593",
            "identifier": "83627465",
            "name": "Permanent Resident Card",
            "description": "Government of Example Permanent Resident Card.",
            "issuanceDate": "2019-12-03T12:19:52Z",
            "expirationDate": "2029-12-03T12:19:52Z",
            "credentialSubject": {"test": 2},
            "proof": {
                "type": "BbsBlsSignature2020",
                "created": "2020-10-16T23:59:31Z",
                "proofPurpose": "assertionMethod",
                "proofValue": "kAkloZSlK79ARnlx54tPqmQyy6G7/36xU/LZgrdVmCqqI9M0muKLxkaHNsgVDBBvYp85VT3uouLFSXPMr7Stjgq62+OCunba7bNdGfhM/FUsx9zpfRtw7jeE182CN1cZakOoSVsQz61c16zQikXM3w==",
                "verificationMethod": "did:example:489398593#test",
            },
        }
        test_constraint = {
            "limit_disclosure": "required",
            "fields": [
                {
                    "path": [
                        "$.credentialSubject.test",
                        "$.vc.credentialSubject.test",
                        "$.test",
                    ],
                    "purpose": "The claim must be from one of the specified issuers",
                    "filter": {"type": "number", "exclusiveMaximum": 2.5},
                }
            ],
        }
        with pytest.raises(DIFPresExchError):
            await dif_pres_exch_handler.filter_constraints(
                credentials=[dif_pres_exch_handler.create_vcrecord(test_cred)],
                constraints=Constraints.deserialize(test_constraint),
            )

    @pytest.mark.asyncio
    async def test_get_did_info_for_did(self, profile):
        dif_pres_exch_handler = DIFPresExchHandler(profile)
        test_did_key = "did:key:z6Mkgg342Ycpuk263R9d8Aq6MUaxPn1DDeHyGo38EefXmgDL"
        with pytest.raises(WalletNotFoundError):
            await dif_pres_exch_handler._did_info_for_did(test_did_key)
