from io import BytesIO
from traceback import format_exc

from flask import request, make_response
from flask_restful import Resource
from pylon.core.tools import log
from sqlalchemy import and_

from ...models.results import SecurityResultsDAST
from tools import auth, LokiLogFetcher, MinioClient


# from ...models.security_reports import SecurityReport


class API(Resource):
    url_params = [
        '<int:project_id>/<int:test_id>',
    ]

    def __init__(self, module):
        self.module = module

    @auth.decorators.check_api({
        "permissions": ["security.app.tests.create"],
    })
    def put(self, project_id: int, test_id: int):
        args = request.json
        test_status = args.get("test_status")

        if not test_status:
            return {"message": "There's not enough parameters"}, 400

        if isinstance(test_id, int):
            _filter = and_(
                SecurityResultsDAST.project_id == project_id, SecurityResultsDAST.id == test_id
            )
        else:
            _filter = and_(
                SecurityResultsDAST.project_id == project_id,
                SecurityResultsDAST.test_uid == test_id
            )
        test = SecurityResultsDAST.query.filter(_filter).first()
        test.set_test_status(test_status)

        if test_status['status'].lower().startswith('finished'):
            test.update_severity_counts()
            test.update_status_counts()
            test.update_findings_counts()
            test.commit()

            write_test_run_logs_to_minio_bucket(test)

        return make_response(
            {"message": f"Status for test_id={test_id} of project_id: {project_id} updated"},
            200)


def write_test_run_logs_to_minio_bucket(test: SecurityResultsDAST, file_name='log.txt'):
    result_key = test.id
    project_id = test.project_id
    build_id = test.build_id
    # test_name = test.test_name
    #
    logs_query = "{" + f'report_id="{result_key}",project="{project_id}",build_id="{build_id}"' + "}"
    #
    enc = 'utf-8'
    file_output = BytesIO()
    file_output.write(f'Test {test.test_name} (id={test.test_id}) run log:\n'.encode(enc))
    llf = LokiLogFetcher.from_project(project_id)
    #
    try:
        llf.fetch_logs(query=logs_query)
        llf.to_file(file_output, enc=enc)
        s3_settings = test.test_config.get(
            'integrations', {}).get('system', {}).get('s3_integration', {})
        minio_client = MinioClient.from_project_id(test.project_id, **s3_settings)
        # bucket_name = str(test_name).replace("_", "").replace(" ", "").lower()
        # if bucket_name not in minio_client.list_bucket():
        #     minio_client.create_bucket(bucket=bucket_name, bucket_type='autogenerated')
        file_name = f"{build_id}.log"
        minio_client.upload_file(test.bucket_name, file_output, file_name)
        return file_name
    except:
        log.warning('Request to loki failed with error %s', format_exc())