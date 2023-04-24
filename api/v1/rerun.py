from flask import make_response
from flask_restful import Resource
from tools import auth
from ...models.tests import SecurityTestsDAST
from ...utils import run_test


class API(Resource):
    url_params = [
        '<int:security_results_dast_id>',
    ]

    def __init__(self, module):
        self.module = module

    @auth.decorators.check_api({
        "permissions": ["security.app.tests.create", "security.app.tests.edit"],
    })
    def post(self, security_results_dast_id: int):
        """
        Post method for re-running test
        """

        test_result = self.module.results_or_404(security_results_dast_id)
        test_config = test_result.test_config

        test = SecurityTestsDAST.query.get(test_config['id'])
        if not test:
            test = SecurityTestsDAST(
                project_id=test_config['project_id'],
                project_name=test_config['project_name'],
                test_uid=test_config['test_uid'],
                name=test_config['name'],
                description=test_config['description'],

                urls_to_scan=test_config['urls_to_scan'],
                urls_exclusions=test_config['urls_exclusions'],
                scan_location=test_config['scan_location'],
                test_parameters=test_config['test_parameters'],

                integrations=test_config['integrations'],
            )
            test.insert()

        resp = run_test(test)
        return make_response(resp, resp.get('code', 200))
