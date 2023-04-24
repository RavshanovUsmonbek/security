from datetime import datetime

from flask import request, make_response
from flask_restful import Resource
from sqlalchemy import and_, or_, desc
from tools import auth
from ...models.reports import SecurityReport
from ...models.results import SecurityResultsDAST


class API(Resource):
    url_params = [
        '<int:project_id>',
    ]

    def __init__(self, module):
        self.module = module

    @auth.decorators.check_api({
        "permissions": ["security.app.reports.view"],
        "recommended_roles": {
            "default": {"admin": True, "editor": True, "viewer": True},
        }
    })
    def get(self, project_id: int):
        reports = []
        args = request.args
        search_ = args.get("search")
        limit_ = args.get("limit")
        offset_ = args.get("offset")
        scan_type = args.get("type").upper()
        if args.get("sort"):
            sort_rule = getattr(getattr(SecurityResultsDAST, args["sort"]), args["order"])()
        else:
            sort_rule = SecurityResultsDAST.id.desc()
        if not args.get("search") and not args.get("sort"):
            total = SecurityResultsDAST.query.filter(
                and_(SecurityResultsDAST.project_id == project_id,
                     SecurityResultsDAST.scan_type == scan_type)
            ).order_by(sort_rule).count()
            res = SecurityResultsDAST.query.filter(
                and_(SecurityResultsDAST.project_id == project_id,
                     SecurityResultsDAST.scan_type == scan_type)
            ).order_by(sort_rule).limit(limit_).offset(offset_).all()
        else:
            filter_ = and_(SecurityResultsDAST.project_id == project_id,
                           SecurityResultsDAST.scan_type == scan_type,
                           or_(SecurityResultsDAST.project_name.like(f"%{search_}%"),
                               SecurityResultsDAST.app_name.like(f"%{search_}%"),
                               SecurityResultsDAST.scan_type.like(f"%{search_}%"),
                               SecurityResultsDAST.environment.like(f"%{search_}%")))
            res = SecurityResultsDAST.query.filter(filter_).order_by(sort_rule).limit(
                limit_).offset(offset_).all()
            total = SecurityResultsDAST.query.filter(filter_).order_by(sort_rule).count()
        for each in res:
            each_json = each.to_json()
            each_json["scan_time"] = each_json["scan_time"].replace("T", " ").split(".")[0]
            each_json["scan_duration"] = float(each_json["scan_duration"])
            reports.append(each_json)
        return make_response({"total": total, "rows": reports}, 200)

    @auth.decorators.check_api({
        "permissions": ["security.app.reports.delete"],
        "recommended_roles": {
            "default": {"admin": True, "editor": False, "viewer": False},
        }
    })
    def delete(self, project_id: int):
        args = request.args
        # project = Project.get_or_404(project_id)
        project = self.module.context.rpc_manager.call.project_get_or_404(project_id)
        for each in SecurityReport.query.filter(
                and_(SecurityReport.project_id == project.id,
                     SecurityReport.report_id.in_(args["id[]"]))
        ).order_by(SecurityReport.id.asc()).all():
            each.delete()
        for each in SecurityResultsDAST.query.filter(
                SecurityResultsDAST.id.in_(args["id[]"])
        ).order_by(SecurityResultsDAST.id.asc()).all():
            each.delete()
        return {"message": "deleted"}

    @auth.decorators.check_api({
        "permissions": ["security.app.reports.create"],
        "recommended_roles": {
            "default": {"admin": True, "editor": True, "viewer": False},
        }
    })
    def post(self, project_id: int):
        args = request.json
        self.module.context.rpc_manager.call.project_get_or_404(project_id)

        # TODO move sast/dast quota checks to a new endpoint, which will be triggered before the scan
        if args["scan_type"].lower() == 'sast':
            if not self.module.context.rpc_manager.call.project_check_quota(project_id,
                                                                            'sast_scans'):
                return make_response(
                    {
                        "Forbidden": "The number of sast scans allowed in the project has been exceeded"},
                    400
                )
        elif args["scan_type"].lower() == 'dast':
            if not self.module.context.rpc_manager.call.project_check_quota(project_id,
                                                                            'dast_scans'):
                return make_response(
                    {
                        "Forbidden": "The number of dast scans allowed in the project has been exceeded"},
                    400
                )

        # monkey patch security results getter
        report = SecurityResultsDAST.query.filter(
            SecurityResultsDAST.project_id == project_id).order_by(
            desc(SecurityResultsDAST.id)).first()

        upd = dict(
            scan_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            # project_id=project.id,
            scan_duration=args["scan_time"],
            # project_name=args["project_name"],
            app_name=args["app_name"],
            dast_target=args["dast_target"],
            sast_code=args["sast_code"],
            scan_type=args["scan_type"],
            findings=args["findings"] - (args["false_positives"] + args["excluded"]),
            false_positives=args["false_positives"],
            excluded=args["excluded"],
            info_findings=args["info_findings"],
            environment=args["environment"]
        )

        for k, v in upd.items():
            setattr(report, k, v)

        report.commit()

        if args["scan_type"].lower() == 'sast':
            self.module.context.rpc_manager.call.increment_statistics(project_id, 'sast_scans')
        elif args["scan_type"].lower() == 'dast':
            self.module.context.rpc_manager.call.increment_statistics(project_id, 'dast_scans')

        return make_response({"id": report.id}, 200)
