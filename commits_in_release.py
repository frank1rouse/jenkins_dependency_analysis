#!/usr/bin/env python
'''
Created on Dec 3, 2015

@author: rousef
'''

import os.path
import sys
import time
import calendar
import subprocess


# GLOBALS
#Booleans
DEBUG = ''
CHART_TITLE = ''
CATCHUP_CHART= ''
REINTEGRATE_CHART= ''
SKIP_REINTEGRATE_MERGE= ''

repo_commits = {}
REMOVE_REVISIONS = []
REMOVE_USERID_COMMITS = []
no_branch_created_repos = []
no_changes_in_branch_repos = []
build_team_only_changes_repo = []
crucible_to_svn_repository_mapping = {'compliance'     :'Vision_Compliance',
                                      'converged_shell':'Vision_Converged_Shell',
                                      'dds'            :'Vision_DDS',
                                      'devops'         :'Vision_DevOps',
                                      'fm'             :'Vision_Foundation_Management',
                                      'panorama'       :'Vision_Panorama',
                                      'sdk'            :'Vision_SDK',
                                      'services'       :'Vision_Services',
                                      'support'        :'Vision_Support',
                                      'tech_alerts'    :'Vision_Tech_Alerts',
                                      'vcops'          :'Vision_VCops',
                                      'vsphere-plugin' :'Vision_VSphere_Plugin',
                                      'webui'          :'Vision_WebUI'}

#Time based variables
SECONDS_IN_A_DAY=86400
SVN_TIME_DATE_FORMAT  = '%Y-%m-%d %H:%M:%S'
FILE_TIMESTAMP_FORMAT = '%Y-%m-%d_%H_%M_%S'
CURRENT_EPOCH_SECONDS=calendar.timegm(time.gmtime())
REPORT_GENERATED_TIME=time.strftime(FILE_TIMESTAMP_FORMAT)

#Strings
branch = ''
HTML_REPORT_FILE_NAME = 'release_commits_report.html'
SVNROOT = 'https://teamforge-vce.usd.lab.emc.com/svn/repos/'
CRUCIBLE_CHANGELOG='https://crucible.ent.vce.com/changelog/'


def main():
    global DEBUG
    branch = ''
    repos = []
    try:
        DEBUG = os.environ["DEBUG"]
        # In case this is passed from jenkins.
        if DEBUG == 'false':
            DEBUG=''
    except KeyError:
        pass

    try:
        branch = os.environ["BRANCH"]
        temp_repos  = os.environ["REPOS"].split(',')
        # Remove the spaces
        for repo in temp_repos:
            repos.append(repo.replace(' ',''))
        repos.sort()
    except KeyError:
        print 'The following environment variables must be set.'
        print ''
        print 'REPOS'
        print '       example REPOS="compliance, fm, sdk"'
        print 'BRANCH'
        print '       example BRANCH="branches/3.2.0"'
        sys.exit(1)
 
    try:
        temp_userid_list = os.environ["REMOVE_USERID_COMMITS"].split(',')
        # Remove the spaces
        for userid in temp_userid_list:
            REMOVE_USERID_COMMITS.append(userid.replace(' ',''))
    except KeyError:
        pass
 
    try:
        temp_revision_list = os.environ["REMOVE_REVISIONS"].split(',')
        # Remove the spaces
        for revision in temp_revision_list:
            REMOVE_REVISIONS.append('r'+revision.replace(' ',''))
    except KeyError:
        pass

    # Sort the repos so that they always are generated in the same order
    repos.sort()

    print ''
    print 'Report generated on ' + REPORT_GENERATED_TIME
    print ''

    print 'branch = ' + branch
    print ''

    if REMOVE_USERID_COMMITS:
        print 'Build team userid commits removed from consideration = ' + str(REMOVE_USERID_COMMITS)
        print ''

    if REMOVE_REVISIONS:
        print 'Revision commits explicitly removed from consideration = ' + str(REMOVE_REVISIONS)
        print ''

    repo_commits = get_commit_log_info(repos, branch)
    print '--------------------------------------------------'
 
    if no_branch_created_repos:
        print 'Repositories without supplied branch'
        print ''
        for repo in no_branch_created_repos:
            print '    ' + repo
        print ''
        print ''

    if no_changes_in_branch_repos:
        print 'Repositories with supplied branch but no changes'
        print ''
        for repo in no_changes_in_branch_repos:
            print '    ' + repo
        print ''
        print ''

    if build_team_only_changes_repo:
        print 'Repositories with supplied branch but build team only changes'
        print ''
        for repo in build_team_only_changes_repo:
            print '    ' + repo
        print ''
        print ''

    if repo_commits:
        print 'Repositories with commits'
        print ''
        sorted_repos = sorted(repo_commits.keys())
        for repo in sorted_repos:
            print '    ' + repo +  ' ' * (45 - len(repo)) + ' ' * ( 4 - len(str(len(repo_commits.get(repo))))) + str(len(repo_commits.get(repo))) + ' change(s)'
        print ''
        print ''
        print 'Commit Details'
        print ''
        for repo in sorted_repos:
            print '    ' + repo
            single_repo = repo_commits.get(repo)
            commits = sorted(single_repo.keys())
            for commit in commits:
                single_commit = single_repo.get(commit)
                author    = single_commit[0]
                date_time = single_commit[1]
                comments  = single_commit[3]
                print '        ' + commit[1:] + ' ' * (8 - len(commit)) + author + ' ' * (12 - len(author)) + comments[0]
                for comment_line in comments[1:]:
                    print ' ' * 22 + comment_line
            print ''

    create_html_report(HTML_REPORT_FILE_NAME, branch, repo_commits)
    sys.exit(0)


def commits_since_branch_creation(repo, branch):
    svn_command = 'svn log  --stop-on-copy ' + SVNROOT + repo + '/' + branch
    p = subprocess.Popen(svn_command, stdout=subprocess.PIPE, shell=True)
    (output, err) = p.communicate()
    if p.returncode != 0:
        return -1
    return output.splitlines()


def get_commit_log_info(repo_list, branch):
    global no_branch_created_repos, no_changes_in_branch_repos, build_team_only_changes_repo
    release_commits = {}
    dash_separator = '------------------------------------------------------------------------'
    # Loop through all of the repos and generate data as you go.
    for repo in repo_list:
        if DEBUG:
            print 'Working with repo "' + repo + '"'

        branch_commits = commits_since_branch_creation(repo, branch)
        if branch_commits == -1:
            no_branch_created_repos.append(repo)
            if DEBUG:
                print '                   No branch "' + branch + '" created for this repository'

        elif not len(branch_commits):
            no_changes_in_branch_repos.append(repo)
            if DEBUG:
                print '                       No commits in branch "' + branch + '" for this repository'

        else:
            comments = []
            revision = ''
            revisions = {}
            revision_info = []

            first_empty_line = True
            build_team_only_changes = False

            # Remove the first dash line from consideration to simplify the parsing.
            for line in branch_commits[1:]:
                if line == dash_separator:
                    revision_info.append(comments)
                    if not build_team_only_changes:
                        revisions.update({revision:revision_info})
                    # Reset the variables for the next run through
                    revision = ''
                    comments = []
                    first_empty_line = True
                    build_team_only_changes = False
                else:
                    # Deal with the empty line.
                    if line == '' and first_empty_line:
                        first_empty_line = False
                        continue
                    # If the revision_info hasn't already been recorded
                    elif not revision:
                        # Example line below
                        # r5004 | rousef | 2015-11-12 16:07:28 -0500 (Thu, 12 Nov 2015) | 1 line
                        # Array with [revision, userid, date_time, timezone
                        revision_split = line.split()
                        revision = revision_split[0]
                        author   = revision_split[2]
                        date     = revision_split[4]
                        time     = revision_split[5]
                        timezone = revision_split[6]
                        revision_info = [author, date + ' ' + time, timezone]
                        if author in REMOVE_USERID_COMMITS or revision in REMOVE_REVISIONS:
                            build_team_only_changes = True
                    else:
                        comments.append(line)
            if len(revisions):
                release_commits.update({repo:revisions})
                if DEBUG:
                    print '                   There are "' + str(len(revisions)) + ' change(s) in the branch ' + branch + '" for this repository'
            else:
                build_team_only_changes_repo.append(repo)
                if DEBUG:
                    print '                   Build team only changes in branch "' + branch + '" for this repository'
    return release_commits

def create_html_report(html_report_name, branch, repo_commits):
    print 'Creating html report.'

    # If we find an existing file just erase as we don't know what state the file was left.
    if os.path.isfile(html_report_name):
        os.remove(html_report_name)
    html_file = open(html_report_name, 'w')


    create_html_list_header(html_file, 'Commits in "' + branch + '" branch.')
    # Write the top level Text
    html_file.write('  <br>\n')
    html_file.write('  <h4>Report created on ' + REPORT_GENERATED_TIME +'</h4>\n')

    if no_branch_created_repos:
        html_file.write('<h5>Branch does not exist.</h5>\n')
        html_file.write('  <ul>\n')
        for repo in no_branch_created_repos:
            html_file.write('    <li>' + repo + '</li>\n')
        html_file.write('  </ul>\n')

    if no_changes_in_branch_repos:
        html_file.write('<h5>Branch exists but there are no changes.</h5>\n')
        html_file.write('  <ul>\n')
        for repo in no_changes_in_branch_repos:
            html_file.write('    <li>' + repo + '</li>\n')
        html_file.write('  </ul>\n')

    if build_team_only_changes_repo:
        html_file.write('<h5>Branch exists but all changes are from build team.</h5>\n')
        html_file.write('  <ul>\n')
        for repo in build_team_only_changes_repo:
            html_file.write('    <li>' + repo + '</li>\n')
        html_file.write('  </ul>\n')

    if repo_commits:
        html_file.write('<h5>Repositories with commits.</h5>\n')
        html_file.write('  <table class="sortable" border=1>\n')
        html_file.write('    <thead>\n')
        html_file.write('      <tr style="color: black; background: lightgray;">\n')
        html_file.write('        <th>Repository</th>\n')
        html_file.write('        <th>Number of Commits</th>\n')
        html_file.write('      </tr>\n')
        html_file.write('    </thead>\n')
        html_file.write('    <tbody>\n')
        sorted_repos = sorted(repo_commits.keys())
        for repo in sorted_repos:
            html_file.write('      <tr>\n')
            html_file.write('        <td><a href="#' + repo + '">' + repo + '</td>\n')
            html_file.write('        <td>' + str(len(repo_commits.get(repo))) +'</td>\n')
            html_file.write('      </tr>\n')
        html_file.write('    </tbody>\n')
        html_file.write('  </table>\n')

        html_file.write('<h5>All Repositories Commit Details.</h5>\n')
        sorted_repos = sorted(repo_commits.keys())

        html_file.write('  <table class="sortable" border=1>\n')
        html_file.write('    <thead>\n')
        html_file.write('      <tr style="color: black; background: lightgray;">\n')
        html_file.write('        <th width="240">Repository</th>\n')
        html_file.write('        <th>Revision</th>\n')
        html_file.write('        <th width="80">Author</th>\n')
        html_file.write('        <th width="140">Date Time</th>\n')
        html_file.write('        <th>Comments</th>\n')
        html_file.write('      </tr>\n')
        html_file.write('    </thead>\n')
        html_file.write('    <tbody>\n')

        sorted_repos = sorted(repo_commits.keys())
        for repo in sorted_repos:
            # Map the subversion repository name to Crucible name
            simple_repo = repo.split('/')[0]
            crucible_repo = crucible_to_svn_repository_mapping.get(simple_repo)
            single_repo = repo_commits.get(repo)
            commits = sorted(single_repo.keys())
            for commit in commits:
                single_commit = single_repo.get(commit)
                author = single_commit[0]
                date_time = single_commit[1]
                comments = single_commit[3]
                comment_lines = comments[0]
                for comment in comments[1:]:
                    comment_lines = comment_lines + '/n' + comment
                html_file.write('      <tr>\n')
                html_file.write('        <td>' + repo +'</td>\n')
                html_file.write('        <td><a href="' + CRUCIBLE_CHANGELOG + crucible_repo + '?cs=' + commit[1:] + '">' + commit [1:] + '</td>\n')
                html_file.write('        <td>' + author +'</td>\n')
                html_file.write('        <td>' + date_time +'</td>\n')
                html_file.write('        <td>' + comment_lines +'</td>\n')
#                 html_file.write('        <td><a href="http://www.w3schools.com/tags/tag_ul.asp">' + repo + '</td>\n')
                html_file.write('      </tr>\n')
        html_file.write('    </tbody>\n')
        html_file.write('  </table>\n')

        html_file.write('<h5>Commits by Repository.</h5>\n')
        for repo in sorted_repos:
            html_file.write('<a name ="' + repo + '"></a>\n')
            html_file.write('<h5>Repo ' + repo + '</h5>\n')

            # Map the subversion repository name to Crucible name
            simple_repo = repo.split('/')[0]
            crucible_repo = crucible_to_svn_repository_mapping.get(simple_repo)

            html_file.write('  <table class="sortable" border=1>\n')
            html_file.write('    <thead>\n')
            html_file.write('      <tr style="color: black; background: lightgray;">\n')
            html_file.write('        <th width="240">Repository</th>\n')
            html_file.write('        <th>Revision</th>\n')
            html_file.write('        <th width="80">Author</th>\n')
            html_file.write('        <th width="140">Date Time</th>\n')
            html_file.write('        <th>Comments</th>\n')
            html_file.write('      </tr>\n')
            html_file.write('    </thead>\n')
            html_file.write('    <tbody>\n')
            single_repo = repo_commits.get(repo)
            commits = sorted(single_repo.keys())
            for commit in commits:
                single_commit = single_repo.get(commit)
                author = single_commit[0]
                date_time = single_commit[1]
                comments = single_commit[3]
                comment_lines = comments[0]
                for comment in comments[1:]:
                    comment_lines = comment_lines + '/n' + comment
                html_file.write('      <tr>\n')
                html_file.write('        <td>' + repo +'</td>\n')
                html_file.write('        <td><a href="' + CRUCIBLE_CHANGELOG + crucible_repo + '?cs=' + commit[1:] + '">' + commit [1:] + '</td>\n')
                html_file.write('        <td>' + author +'</td>\n')
                html_file.write('        <td>' + date_time +'</td>\n')
                html_file.write('        <td>' + comment_lines +'</td>\n')
                html_file.write('      </tr>\n')
            html_file.write('    </tbody>\n')
            html_file.write('  </table>\n')
    create_html_end_of_report(html_file)


def create_html_list_header(html_file, title_text):
    html_file.write('<!DOCTYPE html>\n')
    html_file.write('<html>\n')
    html_file.write('<head>\n')
    html_file.write('<meta charset="ISO-8859-1">\n')
    html_file.write('<title>' + title_text + '</title>\n')
    html_file.write('<script src="sorttable.js"></script>\n')
    html_file.write('<link rel="shortcut icon" href="table.png">')
    html_file.write('<style>\n')
    html_file.write('tr:nth-of-type(odd) {\n')
    html_file.write('background-color: lightgreen;\n')
    html_file.write('}\n')
    html_file.write('tr:nth-of-type(even) {\n')
    html_file.write('  background-color: #A3FF4B;\n')
    html_file.write('}\n')
    html_file.write('  .build_order_width {\n')
    html_file.write('    width: 110px;\n')
    html_file.write('  }\n')
    html_file.write('  .build_job_width {\n')
    html_file.write('    width: 320px;\n')
    html_file.write('  }\n')
    html_file.write('</style>\n')
    html_file.write('</head>\n')
    html_file.write('<body>\n')
    html_file.write('<h2 align="center">'+title_text+'</h2>\n')


def create_html_end_of_report(html_file):
    html_file.write('  <br>\n')
    html_file.write('  <br>\n')
    html_file.write('  <h4>Report created on ' + REPORT_GENERATED_TIME +'</h4>\n')
    html_file.write('</body>\n')
    html_file.write('</html>\n')

if __name__ == '__main__':
    status = main()
    sys.exit(status)
