"""Match-review routes on the shared localhost service; no recorder or game attachment."""
from pathlib import Path
import sqlite3
import webbrowser

from local_service import LocalService,RequestError,Response
from match_adjudication import ConflictError,save_adjudication
from match_review import load_matches,render_review,write_review


def create_service(database, html_path=None, port=0):
    database=Path(database).resolve()
    if not database.is_file():raise ValueError('Match database not found')
    service=LocalService(port=port)

    def page(_):
        matches=load_matches(database)
        if html_path is not None:write_review(matches,html_path,database)
        return Response(render_review(matches,database,service.token))

    def adjudicate(body):
        if set(body) not in ({'match_id','winning_team','reason'},{'match_id','winning_team','reason','robz'}):
            raise RequestError('Require match_id, winning_team and reason')
        try:
            result=save_adjudication(database,**body)
        except ConflictError as error:raise RequestError(str(error),409)
        except ValueError as error:raise RequestError(str(error),400)
        except sqlite3.OperationalError as error:
            raise RequestError('Database unavailable; retry the same decision after checking the recorder',503) from error
        # Refreshing the file is a separate read-only operation. Saving the decision
        # has already committed; clients can safely retry the identical submission.
        matches=load_matches(database)
        if html_path is not None:
            try:write_review(matches,html_path,database)
            except OSError:result['notice']='Decision saved; static HTML could not be refreshed'
        return dict(result,matches=matches)

    service.routes.update({('GET','/'):page,('GET','/match_review.html'):page,
        ('GET','/api/matches'):lambda _:dict(matches=load_matches(database)),
        ('GET','/health'):lambda _:dict(service='match-review',version=1),
        ('POST','/api/adjudications'):adjudicate})
    return service


def serve(database, html_path=None, open_browser=True, port=0):
    with create_service(database,html_path,port=port) as service:
        print(f'Match review: {service.origin}/match_review.html',flush=True)
        print('Keep this terminal open. Refresh the browser for latest data. Ctrl+C stops the service.',flush=True)
        if open_browser:webbrowser.open(service.origin+'/match_review.html')
        try:service.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:pass
