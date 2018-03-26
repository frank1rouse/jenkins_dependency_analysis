#!/usr/bin/env python
'''

@author: rousef
'''

import sys
import json
import time
import hashlib
import os.path
import urllib2
import base64
import socket
import difflib
import smtplib
import StringIO
import pprint
import hashlib
# import subprocess
import ConfigParser
# from xml.dom import minidom
from email.mime.text import MIMEText
from xml.parsers.expat import ExpatError
from xml.dom.expatbuilder import parseString
from __builtin__ import str
from pip._vendor.requests.exceptions import HTTPError

USERID = ''
PASSWORD = ''
DEBUG=False
svn_auth_string = ''
jenkins_auth_string = ''
indent_spaces = '    '
FIRST_COLUMN = 80

# GLOBAL job names
# Will be supplied on the command line
GENISIS_BUILD_JOB = ''

# We can only send emails when running on the Jenkins host machine
# JENKINS_HOST='jenkins.lab.vce.com'
JENKINS_HOST='jenkins.lab.vce.com'
JENKINS_SITE='http://' + JENKINS_HOST + ':8080/jenkins/'
JENKINS_JOBS=JENKINS_SITE + 'job/'
JENKINS_LAST_SUCCESSFUL_BUILD_XML='/lastSuccessfulBuild/api/xml'
JENKINS_LAST_SUCCESSFUL_BUILD_JSON='/lastSuccessfulBuild/api/json'
# Provided in the password properties file.
SMTP_SERVER = '10.3.10.13'
EMAIL_FROM='pebuildrelease@vce.com'
EMAIL_SUBJECT='Changes in the build order file.'
EMAIL_RECEIVER_LIST=''


ARTIFACTORY_SITE='http://repo.vmo.lab:8080/artifactory'
VCE_ARTIFACTORY_REPOSITORY=ARTIFACTORY_SITE + '/webapp/#/artifacts/browse/tree/General/libs-release-local/'
CACHED_ARTIFACTORY_REPOSITORY=ARTIFACTORY_SITE + '/webapp/#/artifacts/browse/tree/General/build-repos/'

SUBVERSION_SITE='https://teamforge-vce.usd.lab.emc.com'
SVN_REPOS=SUBVERSION_SITE + '/svn/repos/'

GIT_HUB_AUTH_TOKEN=''
GIT_HUB_SITE='https://eos2git.cec.lab.emc.com'
GIT_HUB_RAW_SITE='https://raw.eos2git.cec.lab.emc.com'
GIT_ORGANIZATION='VCE-Vision'

# The build job extension will be calculated from the GENISIS_BUILD_JOB
DEPENDENCY_JOB = 'dependency_calculator'
MANUAL_DEPENDENCY_FILE = 'manual_dependencies.properties'


SECOND_COLUMN = FIRST_COLUMN + 20
DEPENDENCY_FILE = 'dependencies.properties'
FILE_TIMESTAMP_FORMAT = '%Y-%m-%d_%H_%M_%S'
REPORT_GENERATED_TIME=time.strftime(FILE_TIMESTAMP_FORMAT)


# Convoluted XML Tags
SHELL_TAG='hudson.tasks.Shell'
MAVEN_BUILD_DOC_ROOT='maven2-moduleset'
PROPERTIES_TAG='hudson.model.ParametersDefinitionProperty'
ARTIFACT_COPY_TAG='hudson.plugins.copyartifact.CopyArtifact'
STRING_PARAMETER_TAG='hudson.model.StringParameterDefinition'
SVN_MODULE_LOCATION='hudson.scm.SubversionSCM_-ModuleLocation'
TRIGGER_BUILD='hudson.plugins.parameterizedtrigger.TriggerBuilder'
MULTI_JOB_BUILD='com.tikal.jenkins.plugins.multijob.MultiJobBuilder'
DOWNSTREAM_TRIGGER='hudson.plugins.downstream__ext.DownstreamTrigger'
BLOCKER_BUILD='hudson.plugins.parameterizedtrigger.BlockableBuildTriggerConfig'
NODESTALKER_TAG='com.datalex.jenkins.plugins.nodestalker.wrapper.NodeStalkerBuildWrapper'


# CONDITIONAL_BUILDER_TAG='org.jenkinsci.plugins.conditionalbuildstep.ConditionalBuilder'


build_order = []
shell_jobs  = []
build_order_discrepancy = []

xml_docs = {}
copy_jobs = {}
maven_artifacts = {}
jenkins_artifacts = {}
manual_dependencies = {}
prebuild_maven_jobs = {}
duplicate_build_jobs = {}
build_job_source_path = {}
out_of_build_copy_dict = {}
artifact_to_job_mapping = {}
report_file_differences = {}
build_order_dict_by_name = {}
build_order_dict_by_number = {}
out_of_build_vce_dependency_dict = {}
out_of_build_manual_dependency_dict = {}
build_jobs_with_maven_version_change_dict = {}



def help_message():
    print 'Usage:'
    print os.path.basename(sys.argv[0]) + ' <first_build_file>'
    print 'with either of the additional parameters'
    print '<subversion userid> <subversion password>'
    print 'or'
    print '<path_to_properties_file> with the following entries'
    print 'userid:<subversion userid>'
    print 'password:<subversion password>'
    print ''

    sys.exit(1)

def resolve_jenkins_string_parameter(xml_snippet, jenkins_string_parameter):
    # Remove the first '$' character
    jenkins_string_parameter = jenkins_string_parameter[1:]
    jenkins_string_parameter.replace('{','')
    jenkins_string_parameter.replace('}','')
    jenkins_build_parameters = xml_snippet.getElementsByTagName(ARTIFACT_COPY_TAG)


# There can be multiple copy artifact snippets so loop through and gather them all
def pull_projects_from_CopyArtifact(xml_snippet):
    copy_artifact_projects= []
    copy_artifacts = xml_snippet.getElementsByTagName(ARTIFACT_COPY_TAG)
    for copy_artifact in copy_artifacts:
        # Make sure there is a project associated with this copy
        if copy_artifact.getElementsByTagName('project')[0].firstChild:
            copy_artifact_project = copy_artifact.getElementsByTagName('project')[0].firstChild.data
            if not (copy_artifact_project.startswith('dependency_calculator') or copy_artifact_project.startswith('get.committers')):
                # Make sure there is a filter associated with this copy
                # Resolve parameter if it's used.
                if copy_artifact_project.startswith('$'):
                   copy_artifact_project = get_Jenkins_parameter_value(xml_snippet, copy_artifact_project)
                if copy_artifact.getElementsByTagName('filter')[0].firstChild:
                    file_filter = copy_artifact.getElementsByTagName('filter')[0].firstChild.data
                    # If the target is blank go ahead and create the entry as it default to the top level of the target project
                    target = ''
                    if copy_artifact.getElementsByTagName('target')[0].firstChild:
                        target = copy_artifact.getElementsByTagName('target')[0].firstChild.data
                    copy_artifact_projects.append([copy_artifact_project, file_filter, target])
    return copy_artifact_projects


def process_list_of_jobs(build_job_list, iteration, indent, prebuild_parent):
    build_job_list.sort()
    for build_job in build_job_list:
        build_job = build_job.strip()
        indent_addition = str(iteration)
        if iteration < 10:
            indent_addition = '0' + indent_addition
        if not (len(indent) == len(indent_spaces)):
            indent_addition = '.'+ indent_addition
        new_indent =  indent.strip() + indent_addition + indent_spaces
        # If we know that this is a prebuild build step add it to the prebuild_maven_jobs dictionary
        if prebuild_parent:
            prebuild_maven_jobs[build_job]=prebuild_parent
        parse_build_job(build_job, new_indent)
        iteration = iteration + 1
    return iteration


# Given a list of node build steps loop through and look for trigger/multi builds
# Return the updated iteration variable to accommodate Maven builds which have both pre/post build sections 
def find_and_process_Builders(build_steps, iteration, indent, prebuild_parent):
    global prebuild_maven_jobs
    for build_step in build_steps:
        # Ignore the ELEMENT_NODE types
        if build_step.nodeType != build_step.ELEMENT_NODE:
            continue
        projects = []
        trigger_projects_nodes = build_step.getElementsByTagName(TRIGGER_BUILD)
        # If we can pull a trigger node out of the xml_snippet it means that the build was encapsulated
        # in a conditional build so we must gather the trigger elements from the build
        if len(trigger_projects_nodes):
            build_step = trigger_projects_nodes[0]
        if build_step.nodeName == TRIGGER_BUILD:
            configs = build_step.getElementsByTagName('configs')[0]
            # There can be a misconfiguration in which a trigger build does not contain any trigger projects.
            # Use this wrapper just so the system doens't error when we find this.
            blocker_builds = configs.getElementsByTagName(BLOCKER_BUILD)
            if len(blocker_builds): 
                blocker_build = blocker_builds[0]
                blocker_projects = blocker_build.getElementsByTagName('projects')[0]
                projects = blocker_projects.firstChild.data.split(',')
            else:
                print '*** Found a trigger build without any triggered projects'
            # Strip out any spaces
            projects = [x.strip(' ') for x in projects]
            # Sort the projects as this is the order in which the trigger build will execute.
            projects.sort()
        if build_step.nodeName == MULTI_JOB_BUILD:
            multijob_job_names = build_step.getElementsByTagName('jobName')
            for multijob_job_name in multijob_job_names:
                if multijob_job_name.nodeType != multijob_job_name.ELEMENT_NODE:
                    continue
                # Add the project to the projects array
                projects.append(multijob_job_name.firstChild.nodeValue)
        iteration = process_list_of_jobs(projects, iteration, indent, prebuild_parent)
    return iteration


def find_build_pom(build_job_doc):
    pom_file_path = 'pom.xml'
    # If there is a rootPOM defined, grab that and use as the pom file.
    if build_job_doc.getElementsByTagName('rootPOM'):
        pom_file_path = build_job_doc.getElementsByTagName('rootPOM')[0].firstChild.nodeValue
    # In case someone gets cute and changes the maven file called.
    maven_goal_string = build_job_doc.getElementsByTagName('goals')[0].firstChild.nodeValue
    if '-Dfile=' in maven_goal_string:
        maven_goals = maven_goal_string.split()
        for maven_goal in maven_goals:
            if maven_goal.startswith('-Dfile='):
                pom_file_index = maven_goal.split('=')
                pom_file_path = pom_file_index[1]
    # In case there is a backward slash in the pom file path
    pom_file_path = pom_file_path.replace('\\', '/')
    return pom_file_path


def get_pom_properties(pom_doc):
    properties={}
    # Pull out the properties from the pom and store the values in a dictionary
    # Do this first as it can be used in other portions of the pom
    if pom_doc.getElementsByTagName('properties'):
        for property_child in pom_doc.getElementsByTagName('properties')[0].childNodes:
            if property_child.nodeType == property_child.ELEMENT_NODE:
                property_tag = property_child.tagName
                property_value = ''
                # Check for the existing of the value. An empty property is valid if useless.
                if property_child.firstChild:
                    property_value = property_child.firstChild.nodeValue.strip()
                properties[property_tag]=property_value
    return properties


def resolve_version(input_string, input_properties, current_project_version, scm_info, pom_file_path, has_parent, group_id):
    temp_property = input_string[input_string.index('${')+2:input_string.index('}')]
    # This means that we were able to get the variable from the input_string
    if temp_property:
        if 'project.version' in temp_property or 'project.parent.version' in temp_property or 'parent.version' in temp_property or temp_property =='version':
            input_string = current_project_version
        else:
            # If we can find the property in the local properties file
            if input_properties.get(temp_property,''):
                input_string = input_properties.get(temp_property)
                if 'project.version' in input_string or 'project.parent.version' in input_string:
                    input_string = current_project_version
            elif has_parent:
                # remove off last pom entry
                parent_pom_file_path = pom_file_path[0:pom_file_path.index('/pom.xml')]
                # Remove last pom entry
                parent_pom_file_path = parent_pom_file_path[0:parent_pom_file_path.rindex('/')]
                parent_pom_file_path = parent_pom_file_path + '/pom.xml'

                pom_doc = get_xml_doc_from_scm(scm_info, parent_pom_file_path)

                if pom_doc.getElementsByTagName('parent'):
                    has_parent = True
                input_properties = get_pom_properties(pom_doc)
                input_string = resolve_version(input_string, input_properties, current_project_version, scm_info, parent_pom_file_path, has_parent, group_id)
    return input_string


def parse_maven_pom(scm_paths, pom_file_path):

    version = ''
    artifactId = ''

    artifacts = []
    properties = {}
    dependencies = []
    vce_dependencies = []
    has_parent = False

    pom_doc = get_xml_doc_from_scm(scm_paths[0], pom_file_path)

    # Loop through all of the top level elements and pull out relevant information
    for child in pom_doc.documentElement.childNodes:
        if child.nodeType == child.ELEMENT_NODE:
            if child.tagName == 'version':
                if child.firstChild:
                    version = child.firstChild.nodeValue.strip()
            if child.tagName == 'artifactId':
                if child.firstChild:
                    artifactId = child.firstChild.nodeValue.strip()

    # Pull out the properties from the pom and store the values in a dictionary
    # Do this first as it can be used in other portions of the pom
    if pom_doc.getElementsByTagName('properties'):
        for property_child in pom_doc.getElementsByTagName('properties')[0].childNodes:
            if property_child.nodeType == property_child.ELEMENT_NODE:
                property_tag = property_child.tagName
                property_value = ''
                # Check for the existing of the value. An empty property is valid if useless.
                if property_child.firstChild:
                    property_value = property_child.firstChild.nodeValue.strip()
                properties[property_tag]=property_value

    # If there is a parent tag we have to check to make sure we are using the artifactId from that
    if pom_doc.getElementsByTagName('parent'):
        has_parent = True
        parent_elements = pom_doc.getElementsByTagName('parent')[0].childNodes
        for parent_element in parent_elements:
            if parent_element.nodeType == parent_element.ELEMENT_NODE:
                if not artifactId and parent_element.tagName == 'artifactId':
                    # Now that we know we have used the parent artifactId select the second artifactId from getElementsByTagName
                    if parent_element.firstChild.nodeValue == artifactId:
                        artifactId = pom_doc.getElementsByTagName('artifactId')[1].firstChild.nodeValue
                if not version and parent_element.tagName == 'version' and parent_element.firstChild:
                    version = parent_element.firstChild.nodeValue.strip()

    packaging = 'jar'
    # If the packaging is explicitly set use that
    if len(pom_doc.getElementsByTagName('packaging')):
        packaging = pom_doc.getElementsByTagName('packaging')[0].firstChild.nodeValue
    groupId = pom_doc.getElementsByTagName('groupId')[0].firstChild.nodeValue

    # If we get to this point and the version is still a variable we need to update it.
    if '${' in version:
        version = resolve_version(version, properties, version, scm_paths[0], pom_file_path, has_parent, groupId)

    artifact = [artifactId, version, packaging, groupId]
    print ' ' * (FIRST_COLUMN + 10) + 'Adding artifact ' + str(artifact)
    artifacts.append(artifact)


    # Loop through all of the dependencies and record any dependencies that start with com.vce
    if pom_doc.getElementsByTagName('dependencies'):
        for dependency in pom_doc.getElementsByTagName('dependencies')[0].getElementsByTagName('dependency'):
            dependency_groupId     = ''
            dependency_artifiactId = ''
            dependency_version     = ''
            if dependency.getElementsByTagName('groupId'):
                dependency_groupId = dependency.getElementsByTagName('groupId')[0].firstChild.nodeValue
                if '${project.groupId}' in dependency_groupId:
                    dependency_groupId = groupId
            if dependency.getElementsByTagName('artifactId'):
                dependency_artifiactId = str(dependency.getElementsByTagName('artifactId')[0].firstChild.nodeValue)
            if dependency.getElementsByTagName('version'):
                dependency_version = str(dependency.getElementsByTagName('version')[0].firstChild.nodeValue)
                # Resolve any variables in the version element
                if '${' in dependency_version:
                    dependency_version = resolve_version(dependency_version, properties, version, scm_paths[0], pom_file_path, has_parent, dependency_groupId)

            dependency = [dependency_groupId, dependency_artifiactId, dependency_version]
            dependencies.append(dependency)
            if dependency_groupId.startswith('com.vce'):
                vce_dependencies.append(dependency)

    # Check for the existence of modules and if needed process individually
    if pom_doc.getElementsByTagName('modules'):
        parent_path = '/'.join(pom_file_path.split('/')[:-1])
        modules = {}
        # Because there can be modules in several places in the pom loop through all instances and place all modules in dictionary to prevent duplication.
        for module_node_list in pom_doc.getElementsByTagName('modules'):
            for childNode in module_node_list.childNodes:
                if childNode.nodeType == childNode.ELEMENT_NODE:
                    modules[childNode.firstChild.nodeValue.strip()] = ''

        # Now loop through all of the modules and gather information.
        for module in sorted(modules, key=modules.get):
            if not module == '':
                child_path = parent_path + '/' + module + '/pom.xml'
                # There exist other 'modules' elements but this will result in an truncated child_path
                module_artifacts = parse_maven_pom(scm_paths, child_path)
                artifacts.extend(module_artifacts['artifacts'])
                dependencies.extend(module_artifacts['dependencies'])
                vce_dependencies.extend(module_artifacts['vce_dependencies'])
    return {'version':version, 'artifacts':artifacts, 'dependencies':dependencies, 'vce_dependencies':vce_dependencies, 'properties':properties}

def get_subversion_path(build_job_doc):
    subversion_path = ''
    # Find the string parameter that matches the newVersion name and pull the default value from that.
    if build_job_doc.getElementsByTagName(SVN_MODULE_LOCATION):
        for subversion_module in build_job_doc.getElementsByTagName(SVN_MODULE_LOCATION):
            for subversion_module_child in subversion_module.childNodes:
                for subversion_module_grandkids in subversion_module_child.childNodes:
                    if subversion_module_grandkids.parentNode.nodeName == 'remote':
                        # In case of the first subversion path entry
                        if not subversion_path:
                            subversion_path = subversion_module_grandkids.data[len(SVN_REPOS):]
                        # For each additional path separate with a comma space.
                        else:
                            subversion_path += ', ' + subversion_module_grandkids.data[len(SVN_REPOS):]
    # If you've run through all of the properties without finding the  the newVersion property return an empty string.
    return subversion_path


def get_jenkins_artifacts(build_job_name):
    last_successful_build_url_request = urllib2.Request(JENKINS_JOBS + build_job_name + JENKINS_LAST_SUCCESSFUL_BUILD_JSON)
    # There may not be a successful build when first run so catch the error and put a message in the console.
    try: last_successful_build_json_string = urllib2.urlopen(last_successful_build_url_request).read()
    except urllib2.HTTPError:
        print '*** No successful build yet for "' + build_job_name + '" build job.'
        print ''
        return
    parsed_last_succesful_build_json = json.loads(last_successful_build_json_string)
    # Keep the information as a json structure in case we need other elements later
    return parsed_last_succesful_build_json['artifacts']

def get_newVersion_property_value(build_job_doc):
    # Find the string parameter that matches the newVersion name and pull the default value from that.
    if build_job_doc.getElementsByTagName(PROPERTIES_TAG):
        for jenkins_property_child in build_job_doc.getElementsByTagName(PROPERTIES_TAG)[0].childNodes:
            if jenkins_property_child.nodeType == jenkins_property_child.ELEMENT_NODE:
                if jenkins_property_child.tagName == 'parameterDefinitions':
                    for jenkins_property in jenkins_property_child.childNodes:
                        if jenkins_property.nodeType == jenkins_property.ELEMENT_NODE:
                            if jenkins_property.tagName == STRING_PARAMETER_TAG:
                                name_value = jenkins_property.getElementsByTagName('name')[0].firstChild.nodeValue
                                if name_value == 'newVersion':
                                    # As soon as you find the value return from this function
                                    return jenkins_property.getElementsByTagName('defaultValue')[0].firstChild.nodeValue
    # If you've run through all of the properties without finding the  the newVersion property return an empty string.
    return ''


def get_Jenkins_parameter_value(build_job_doc, jenkins_string_parameter):
    # Strip out the first dollar sign character and the braces
    jenkins_string_parameter = jenkins_string_parameter[1:]
    jenkins_string_parameter = jenkins_string_parameter.replace('{','')
    jenkins_string_parameter = jenkins_string_parameter.replace('}','')
    # Find the string parameter that matches the newVersion name and pull the default value from that.
    if build_job_doc.getElementsByTagName(PROPERTIES_TAG):
        for jenkins_property_child in build_job_doc.getElementsByTagName(PROPERTIES_TAG)[0].childNodes:
            if jenkins_property_child.nodeType == jenkins_property_child.ELEMENT_NODE:
                if jenkins_property_child.tagName == 'parameterDefinitions':
                    for jenkins_property in jenkins_property_child.childNodes:
                        if jenkins_property.nodeType == jenkins_property.ELEMENT_NODE:
                            if jenkins_property.tagName == STRING_PARAMETER_TAG:
                                name_value = jenkins_property.getElementsByTagName('name')[0].firstChild.nodeValue
                                if name_value == jenkins_string_parameter:
                                    # As soon as you find the value return from this function
                                    return jenkins_property.getElementsByTagName('defaultValue')[0].firstChild.nodeValue
    # If you've run through all of the properties without finding the  the newVersion property return an empty string.
    return ''


def prebuild_maven_version_change(build_job_doc):
    # Find the string parameter that matches the newVersion name and pull the default value from that.
    if build_job_doc.getElementsByTagName('prebuilders'):
        for prebuilders_child in build_job_doc.getElementsByTagName('prebuilders')[0].childNodes:
            if prebuilders_child.nodeType == prebuilders_child.ELEMENT_NODE:
                if prebuilders_child.tagName == 'hudson.tasks.Maven':
                    targets_value = prebuilders_child.getElementsByTagName('targets')[0].firstChild.nodeValue
                    if targets_value == 'versions:set':
                        # As soon as you find the value return from this function
                        return True
    # If you've run through all of the properties without finding the  the newVersion property return an empty string.
    return False


def retry(ExceptionToCheck, tries=4, delay=3, backoff=2):
    """Retry decorator
    original from http://wiki.python.org/moin/PythonDecoratorLibrary#Retry
    """
    def deco_retry(f):
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 0:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck, e:
                    print "%s, Retrying in %d seconds..." % (str(e), mdelay)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
                    lastException = e
            raise lastException
        return f_retry # true decorator
    return deco_retry


@retry(urllib2.URLError, tries=8, delay=3, backoff=2)
def urlopen_with_retry(url):
    return urllib2.urlopen(url)


# Cache the parsed xml documents in the xml_docs dictionary to reduce number of reads over the wire.
# Use a hash of the scm_info table as well as the file_path as a unique key.
def get_xml_doc_from_scm(scm_info, file_path):
    xml_doc = ''
    sha = hashlib.sha224(str(scm_info)+file_path).hexdigest()
    if sha in xml_docs:
        xml_doc = xml_docs[sha]
    else:    
        url_path = ''
        file_content_string = ''
        if scm_info['type'] == 'subversion':
            url_path = scm_info['url'] + '/' + file_path
            if DEBUG:
                print 'subversion url path = ' + url_path
            svn_url_request = urllib2.Request(url_path)
            # Use the same svn_auth_string as before
            svn_url_request.add_header("Authorization", "Basic %s" % svn_auth_string)
#             try: file_content_string = urllib2.urlopen(svn_url_request.read())
            try: file_content_string = urlopen_with_retry(svn_url_request).read()
            except urllib2.HTTPError:
                print '*** Unable to read subversion path "' + url_path
                print ''
                sys.exit(1)
        elif scm_info['type'] == 'git':
            url_path = GIT_HUB_RAW_SITE + '/' + scm_info['organization'] +  '/' + scm_info['repository'] + '/' + scm_info['branch'] + '/'+ file_path
            if DEBUG:
                print 'git url path = ' + url_path
            git_url_request = urllib2.Request(url_path)
            git_url_request.add_header('Authorization', 'token %s' % GIT_HUB_AUTH_TOKEN)
#             try: response = urllib2.urlopen(git_url_request)
            try: file_content_string = urlopen_with_retry(git_url_request).read()
            except urllib2.HTTPError:
                print '*** Unable to read git path "' + url_path
                print ''
                sys.exit(1)
        elif scm_info['type'] == 'sharedWorkspace':
            url_path = scm_info['url'] + '/ws/' + file_path
            if DEBUG:
                print 'jenkins shared workdspace url path = ' + url_path
            jenkins_job_url_request = urllib2.Request(url_path)
            jenkins_job_url_request.add_header("Authorization", "Basic %s" % jenkins_auth_string)
            try: file_content_string = urlopen_with_retry(jenkins_job_url_request).read()
#             try: file_content_string = urllib2.urlopen(jenkins_job_url_request).read()
            except urllib2.HTTPError:
                print '*** Unable to read jenkins shared workspace path "' + url_path
                print ''
                sys.exit(1)
        elif scm_info['type'] == 'jenkinsConfig':
            url_path = scm_info['url'] + '/' + file_path
            if DEBUG:
                print 'jenkins config url path = ' + url_path
            jenkins_job_url_request = urllib2.Request(url_path)
            jenkins_job_url_request.add_header("Authorization", "Basic %s" % jenkins_auth_string)
            try: file_content_string = urlopen_with_retry(jenkins_job_url_request).read()
#             try: file_content_string = urllib2.urlopen(jenkins_job_url_request).read()
            except urllib2.HTTPError:
                print '*** Unable to read jenkins config url path "' + url_path + '"'
                print ''
                sys.exit(1)
        else:
            print "just a test."
        # Create an XML object and exit if this fails
        try: xml_doc = parseString(file_content_string)
        except ExpatError:
            print 'Malformed XML file at ' + url_path
            sys.exit(0)
        xml_docs[sha] = xml_doc
    return xml_doc


def pull_subversion_info(scm_element):
    scm_item = {}
    scm_item['type'] = 'subversion'
    scm_item['url']  = scm_element.getElementsByTagName('remote')[0].firstChild.nodeValue
    return scm_item


def pull_git_info(scm_element):
    scm_item = {}
    scm_item['type'] = 'git'
    # There should be only a single url element in the git scm_element
    scm_item['url'] = scm_element.getElementsByTagName('url')[0].firstChild.nodeValue
    # Strip any .git extensions
    if scm_item['url'].endswith('.git'):
        scm_item['url'] = scm_item['url'][:-4]
    # String any url ending with the '/' character
    elif scm_item['url'].endswith('/'):
        scm_item['url'] = scm_item['url'][:-1]
    scm_item['repository'] = str(scm_item['url'].split('/')[-1:][0])
    scm_item['organization'] = str(scm_item['url'].split('/')[-2:-1][0])
    # Now we need to grab the branch
    branch_element = scm_element.getElementsByTagName('branches')[0]

    scm_item['branch'] = str(branch_element.getElementsByTagName('name')[0].firstChild.nodeValue).translate(None, "*/\/")
    # If we find the sparseCheckoutPaths element then we need to loop through all of the sparse paths
    sparse_checkout_nodelist = scm_element.getElementsByTagName('sparseCheckoutPaths')
    if len(sparse_checkout_nodelist):
        sparse_checkout_dirs = []
        sparse_checkout_element = scm_element.getElementsByTagName('sparseCheckoutPaths')[0]
        sparse_checkout_dirs_nodelist = sparse_checkout_element.getElementsByTagName('hudson.plugins.git.extensions.impl.SparseCheckoutPath')
        for sparse_checkout_dir_element in sparse_checkout_dirs_nodelist:
            sparse_checkout_dirs.append(sparse_checkout_dir_element.getElementsByTagName('path')[0].firstChild.nodeValue)
        if sparse_checkout_dirs:
            scm_item['sparse_paths'] = sparse_checkout_dirs
    return scm_item


def get_source_path(build_job_doc, build_job_name):

        # Grab all of the scm information in the scm_info_nodelist
    scm_info_nodelist = build_job_doc.getElementsByTagName('scm')

    # Hold all of the scm path information in a list
    scm_paths = []

    # If the class is listed as NullSCM it means that there is no scm information in the element.
    if 'NullSCM' not in scm_info_nodelist[0].attributes['class'].nodeValue:
        # Loop through all of the scm information and save in scm_paths list.
        for scm_element in scm_info_nodelist:
            # Because of the different types of information stored in subversion and git store the information in a hash.
            scm_item = {}
            plugin, plugin_type = scm_element.attributes.items()[1]
            test_plugin = scm_element.attributes['plugin']
            # For subversion all we need in the path to the source code.
            if 'subversion' in plugin_type:
                scm_paths.append(pull_subversion_info(scm_element))
            # For git in addition to the path we need the branch as well as the sparse checkout path if enabled
            elif 'git' in plugin_type:
                scm_paths.append(pull_git_info(scm_element))
            elif 'multiple-scms' in plugin_type:
                for node_list in scm_info_nodelist:
                    git_nodelist = node_list.getElementsByTagName('hudson.plugins.git.GitSCM')
                    for git_node in git_nodelist:
                        scm_paths.append(pull_git_info(git_node))
                    svn_nodelist = node_list.getElementsByTagName('hudson.svn.SubversionSCM')
                    for svn_node in svn_nodelist:
                        scm_paths.append(pull_subversion_info(svn_node))
            else:
                print 'Unknown scm type ' + plugin_type
    # If there is no scm_info then the assumption is that it is a shared workspace
    else:
        # The NODESTALKER_TAG is used to contain information about explicitly shared workspaces.
        # Look for this first as it is the most likely method to share workspaces
        scm_item = {}
        shared_job = ''
        if len(build_job_doc.getElementsByTagName(NODESTALKER_TAG)):
            nodestalker = build_job_doc.getElementsByTagName(NODESTALKER_TAG)[0]
            nodestalker_shareWorkspace = nodestalker.getElementsByTagName('shareWorkspace')[0].firstChild.nodeValue
            if nodestalker_shareWorkspace == 'true':
                shared_job = nodestalker.getElementsByTagName('job')[0].firstChild.nodeValue
                scm_item['type'] = 'sharedWorkspace'
                scm_item['url']  = JENKINS_JOBS + shared_job
        # The other alternative is that a custom workspace is specified in the maven build advanced options.
        elif len(build_job_doc.getElementsByTagName('customWorkspace')):
            remote_location = build_job_doc.getElementsByTagName('customWorkspace')[0].firstChild.nodeValue
            shared_job = os.path.basename(remote_location)
            scm_item['type'] = 'customWorkspace'
            scm_item['url']  = JENKINS_JOBS + shared_job
        else:
            scm_item['type'] = 'noSCM'
        scm_paths.append(scm_item)
    return scm_paths


def parse_build_job(build_job_name, indent):
    # To ensure we are using the global variables
    global build_order, maven_artifacts, jenkins_artifacts, shell_jobs, jenkins_auth_string
    version_change = ''

    scm_item = {'type': 'jenkinsConfig'}
    scm_item['url'] = JENKINS_JOBS + build_job_name 
    build_job_doc = get_xml_doc_from_scm(scm_item, 'config.xml')

    # Grab the copy artifacts jobs and place in the copy_jobs dictionary
    copy_projects = pull_projects_from_CopyArtifact(build_job_doc)
    # If we have anything to add update copy_jobs
    if copy_projects:
        copy_jobs.update({build_job_name:copy_projects})

    # Get the list of generated artifacts from the last successful build.
    build_job_jenkins_artifacts = get_jenkins_artifacts(build_job_name)
    # Make sure we don't have an empty dictionary
    if build_job_jenkins_artifacts and any(build_job_jenkins_artifacts):
        jenkins_artifacts.update({build_job_name:build_job_jenkins_artifacts})

    # If there are any shell jobs list this separately as it could effect dependency.
    if len(build_job_doc.getElementsByTagName(SHELL_TAG)):
        shell_jobs.extend([build_job_name])

    # Save the source path associated with this job for use later
    build_job_source_path[build_job_name] = get_source_path(build_job_doc, build_job_name)

    # If this is a Maven build the length of the document will be zero which works as a false.
    maven_build = len(build_job_doc.getElementsByTagName(MAVEN_BUILD_DOC_ROOT))

    if maven_build:
        build_job = [build_job_name, indent, True]
        build_order.append(build_job)
        print indent + build_job_name + ' ' * (FIRST_COLUMN - len(indent + build_job_name)) + 'Maven job'

        # Full string of the contents of the pom file.
        pom_file_string = ''

        # Find the build pom file path
        pom_file_path = find_build_pom(build_job_doc)
        maven_build_job_info = parse_maven_pom(build_job_source_path[build_job_name], pom_file_path)

        # Check to see if the version has been changed through a maven 'version:set' prebuild job
        if prebuild_maven_version_change(build_job_doc):
            changed_version = get_newVersion_property_value(build_job_doc)
            print 'Changed version for job ' + build_job_name + ' from ' + maven_build_job_info['version'] + ' to ' + changed_version
            build_jobs_with_maven_version_change_dict[build_job_name]=[maven_build_job_info['version'], changed_version]
            # Change the top level version label
            maven_build_job_info['version'] = changed_version
            # Update the version for all of the generated artifacts
            updated_artifacts = maven_build_job_info['artifacts']
            index = 0
            for artifact in updated_artifacts:
                #artifact = [artifactId, version, packaging, groupId]
                # More explicit than it needs to be but it helps me visualize what is happening
                artifactId = artifact[0]
                version    = changed_version
                packaging  = artifact[2]
                groupId    = artifact[3]
                artifact   = [artifactId, version, packaging, groupId]
                updated_artifacts[index] = artifact
                index += 1
            maven_build_job_info['artifacts'] = updated_artifacts

        maven_artifacts.update({build_job_name:maven_build_job_info})

        # Pull both pre and post builders to check for trigger builds.
        iteration = 1
        pre_build_steps = build_job_doc.getElementsByTagName('prebuilders')[0]
        iteration = find_and_process_Builders(pre_build_steps.childNodes, iteration, indent, build_job_name)
        post_build_steps = build_job_doc.getElementsByTagName('postbuilders')[0]
        find_and_process_Builders(post_build_steps.childNodes, iteration, indent, '')
    else:
        build_job = [build_job_name, indent, False]
        build_order.append(build_job)
        print indent + build_job_name

        # Look through the builders for trigger builds
        build_steps = build_job_doc.getElementsByTagName('builders')[0]
        iteration = 1
#         iteration = find_and_process_TriggerBuilders(build_steps.childNodes, iteration, indent, '')
        iteration = find_and_process_Builders(build_steps.childNodes, iteration, indent, '')

        # Grab all of the downstream trigger builds
        downstream_trigger_xml= build_job_doc.getElementsByTagName(DOWNSTREAM_TRIGGER)
        # It's possible that there are no downstream triggers. Check for that here.
        if downstream_trigger_xml: 
            childProjects = downstream_trigger_xml[0].getElementsByTagName('childProjects')[0].firstChild.nodeValue.split(',')
            childProjects = [x.strip(' ') for x in childProjects]
            childProjects.sort()
            process_list_of_jobs(childProjects, iteration, indent, '')


def print_and_write(output_file, text):
    print text
    output_file.write(text + '\n')


def center_header(header_text, spacer_char):
    spacer_num = (80 - len(header_text))/2
    odd_space_addition = ''
    if len(header_text) % 2:
        odd_space_addition = spacer_char
    return spacer_char * spacer_num + header_text + spacer_char * spacer_num + odd_space_addition


def create_new_report_file(report_name):
    # Open a local copy of the build order report file
    new_report_file_name = report_name + '_new'

    # If we find an existing file just erase as we don't know what state the file was left.
    if os.path.isfile(new_report_file_name):
        os.remove(new_report_file_name)
    new_report_file = open(new_report_file_name, 'w')
    return new_report_file


def create_md5sum_file(file_name):
    # compute md5sum
    md5sum = hashlib.md5(open(file_name, 'rb').read()).hexdigest()
    md5_file_name = file_name + '.md5'

    # Remove the existing md5 file
    if os.path.isfile(md5_file_name):
        os.remove(md5_file_name)

    # Create the new md5 file
    md5_file = open(md5_file_name, 'w')
    md5_file.write(str(md5sum))
    md5_file.close()


def compare_new_and_existing_reports(report_file_name):

    diff_text_output = ''
    new_report_file_name = report_file_name + '_new'
    # If the existing report does not exist
    if not os.path.isfile(report_file_name):
        print 'No existing report "' + report_file_name + '" exists.'
        print 'Copy existing new report to "' + report_file_name + '" and create new md5sum file'
        os.rename(new_report_file_name, report_file_name)
        # Create the new md5 file
        create_md5sum_file(report_file_name)
    else:
        last_report_modified_time = time.strftime(FILE_TIMESTAMP_FORMAT,time.localtime(int(round(os.path.getmtime(report_file_name)))))
        old_report_modified_name = report_file_name + '.' + last_report_modified_time
        if not os.path.isfile(report_file_name + '.md5'):
            print 'No existing md5sum file "' + report_file_name + '.md5".'
            print 'Creating md5sum from new report.'
            os.rename(report_file_name, old_report_modified_name)
            os.rename(new_report_file_name, report_file_name)
            create_md5sum_file(report_file_name)
        else:
            new_md5sum = hashlib.md5(open(new_report_file_name, 'rb').read()).hexdigest()
            report_md5sum_file = open(report_file_name + '.md5', 'r')
            report_md5sum = report_md5sum_file.read().strip()
            report_md5sum_file.close()
            if new_md5sum == report_md5sum:
                print 'The old and new reports "' + report_file_name + '" md5sums are the same.'
                print 'Removing the new report as it matches existing report.'
                os.remove(new_report_file_name)
            else:
                print 'Differences in the old and new reports.'
                # Rename the existing report and the new report before the diff
                os.rename(report_file_name, old_report_modified_name)
                os.rename(new_report_file_name, report_file_name)
                # Create a new md5sum file based on the updated file contents
                create_md5sum_file(report_file_name)
                new_file = open(report_file_name, 'r')
                old_file = open(old_report_modified_name, 'r')
                diff = difflib.unified_diff(old_file.readlines(), new_file.readlines(), fromfile=old_file, tofile=new_file)
                report_file_differences[report_file_name]=diff
                for line in diff:
                    print line
                    diff_text_output += str(line) + '\n'
    return diff_text_output


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


def create_build_order_report():
    # To ensure we are using the global variables 
    global build_order, build_order_dict_by_name, duplicate_build_jobs,  GENISIS_BUILD_JOB

    build_order_file_name = GENISIS_BUILD_JOB + '_current_build_order_report'
    print ''
    print ''
    print ''
    print 'Create ' + build_order_file_name
    print ''

    # Open a local copy of the build order report file

    new_build_order_report_file = create_new_report_file(build_order_file_name)

    print_and_write(new_build_order_report_file, center_header(' Root build job "' + GENISIS_BUILD_JOB + '" ', '-'))
    print_and_write(new_build_order_report_file, center_header(' Current Build Order ', '-'))
    print_and_write(new_build_order_report_file, center_header(' ' + str(len(build_order)) + ' total build steps. ', '-'))

    print_and_write(new_build_order_report_file, GENISIS_BUILD_JOB)
    # Skip the first element of the build_order list as it is the GENISIS_BUILD_JOB which we have already printed.
    for build in build_order[1:]:
        build_name   = build[0]
        build_number = build[1]
        scm_info = build_job_source_path.get(build_name)
        source_string = ''
        for scm_item in scm_info:
            if 'noSCM' not in scm_item['type']:
                source_string += scm_item['url'] + ' '
                # TODO Remove the string below as it's not needed anymore
#         subversion_string = build_job_subversion_path.get(build_name)
        source_string = source_string[:-1]
        # Print out the current build job name 
        print_and_write(new_build_order_report_file, build_number + build_name + ' ' * (50 - len(build_number + build_name)) + source_string)
        # Look to see if this job has already been executed
        previously_executed_build_job_info = build_order_dict_by_name.get(build_name,'')
        if previously_executed_build_job_info:
            previously_executed_build_job_number = previously_executed_build_job_info[1].strip()
            if len(previously_executed_build_job_number) == 1:
                previously_executed_build_job_number = '0' + previously_executed_build_job_number
            duplicate_jobs = ''
            duplicate_build_number = build_number.strip()
            if len(duplicate_build_number) > 2:
                duplicate_build_number = duplicate_build_number[:-3] 
            # Check if there is a previous duplicate entry. If so add the latest duplicate to the end of the list.
            previous_duplicate_jobs = duplicate_build_jobs.get(build_name, '')
            if previous_duplicate_jobs:
                duplicate_jobs = previous_duplicate_jobs + ' ' + duplicate_build_number
            else:
                duplicate_jobs = previously_executed_build_job_number + ' ' + duplicate_build_number
            duplicate_build_jobs[build_name]=duplicate_jobs
        build_order_dict_by_name[build_name]=build_number
        build_order_dict_by_number[build_number.strip()]=build_name
        
    new_build_order_report_file.close()

    file_differences = compare_new_and_existing_reports(build_order_file_name)
    build_order_html_file_name = build_order_file_name + '.html'
    
    # Create/Recreate the HTML file if there are differences or the file cannot be found
    if file_differences or not os.path.isfile(build_order_html_file_name):
        
        if os.path.isfile(build_order_html_file_name):
            os.remove(build_order_html_file_name)
        build_order_html_file = open(build_order_html_file_name, 'w')
        title_text = GENISIS_BUILD_JOB + ' Build Order'
        create_html_list_header(build_order_html_file, title_text)

        build_order_html_file.write('  <table class="sortable" border=1>\n')
        build_order_html_file.write('    <thead>\n')
        build_order_html_file.write('      <tr style="color: black; background: lightgray;">\n')
        build_order_html_file.write('        <th><div class="build_order_width">Build Order</div></th>\n')
        build_order_html_file.write('        <th><div class="build_job_width">Build Job</div></th>\n')
        build_order_html_file.write('        <th align="left">&nbsp;&nbsp;Source Path(s)</th>\n')
        build_order_html_file.write('      </tr>\n')
        build_order_html_file.write('    </thead>\n')
        build_order_html_file.write('    <tbody>\n')
        for build in build_order:
            build_name   = build[0]
            build_number = build[1]
            build_order_html_file.write('      <tr>\n')
            build_order_html_file.write('        <td>'+build_number+'</td>\n')
            build_order_html_file.write('        <td><a href="' + JENKINS_JOBS + build_name + '">' + build_name + '</a>\n')
            source_string = ''
            source_list = build_job_source_path.get(build_name)
            for scm_info in build_job_source_path.get(build_name):
                if 'noSCM' not in scm_info['type']:
                    url = scm_info['url']
                    if 'git' in scm_info['type']:
                        url = scm_info['url'] + '/tree/' + scm_info['branch']
                    source_string += '<a href="' + url + '">' + url + '</a>,&nbsp;'
            build_order_html_file.write('        <td>' + source_string + '\n')
            build_order_html_file.write('      </tr>\n')
        build_order_html_file.write('    </tbody>\n')
        build_order_html_file.write('    <tfoot>\n')
        build_order_html_file.write('      <tr>\n')
        build_order_html_file.write('<td>Total build jobs</td>\n')
        build_order_html_file.write('        <td>'+str(len(build_order))+'</td>\n')
        build_order_html_file.write('        <td></td>\n')
        build_order_html_file.write('      </tr>\n')
        build_order_html_file.write('    </tfoot>\n')
        build_order_html_file.write('  </table>\n')
        create_html_end_of_report(build_order_html_file)
        build_order_html_file.close()
    return file_differences


def create_shell_jobs_report():
    # To ensure we are using the global variables 
    global shell_jobs, GENISIS_BUILD_JOB

    shell_jobs_file_name = GENISIS_BUILD_JOB + '_current_shell_jobs_report'
    print ''
    print ''
    print ''
    print 'Create ' + shell_jobs_file_name
    print ''

    new_shell_jobs_report_file = create_new_report_file(shell_jobs_file_name)
    print_and_write(new_shell_jobs_report_file, center_header(' Root build job "' + GENISIS_BUILD_JOB + '" ', '@'))
    print_and_write(new_shell_jobs_report_file, center_header(' List of jobs that contain shell scripts. ','@'))
    print_and_write(new_shell_jobs_report_file, center_header(' ' + str(len(shell_jobs)) + ' total jobs ','@'))

    for shell_job in shell_jobs:
        print_and_write(new_shell_jobs_report_file, shell_job)
    new_shell_jobs_report_file.close()

    file_differences = compare_new_and_existing_reports(shell_jobs_file_name)
    shell_jobs_html_file_name = shell_jobs_file_name + '.html'

    # Create/Recreate the HTML file if there are differences or the file cannot be found
    if file_differences or not os.path.isfile(shell_jobs_html_file_name):

        if os.path.isfile(shell_jobs_html_file_name):
            os.remove(shell_jobs_html_file_name)
        shell_jobs_html_file = open(shell_jobs_html_file_name, 'w')
        title_text = GENISIS_BUILD_JOB + ' Jenkins Jobs With Shell Scripts'
        create_html_list_header(shell_jobs_html_file, title_text)
        shell_jobs_html_file.write('  <table class="sortable" border=1>\n')
        shell_jobs_html_file.write('    <thead>\n')
        shell_jobs_html_file.write('      <tr style="color: black; background: lightgray;">\n')
        shell_jobs_html_file.write('        <th>Jenkins Jobs</th>\n')
        shell_jobs_html_file.write('      </tr>\n')
        shell_jobs_html_file.write('    </thead>\n')
        shell_jobs_html_file.write('    <tbody>\n')
        for shell_job in shell_jobs:
            shell_jobs_html_file.write('      <tr>\n')
            shell_jobs_html_file.write('        <td><a href="' + JENKINS_JOBS + shell_job + '">' + shell_job + '</a>\n') 
            shell_jobs_html_file.write('      </tr>\n')
        shell_jobs_html_file.write('    </tbody>\n')
        shell_jobs_html_file.write('    <tfoot>\n')
        shell_jobs_html_file.write('      <tr>\n')
        shell_jobs_html_file.write('        <td>Total jobs with scripts = ' + str(len(shell_jobs)) + '</td>\n')
        shell_jobs_html_file.write('      </tr>\n')
        shell_jobs_html_file.write('    </tfoot>\n')
        shell_jobs_html_file.write('  </table>\n')
        create_html_end_of_report(shell_jobs_html_file)
        shell_jobs_html_file.close()

    # Return the file differences to use in the email notification if requested.
    return file_differences


def create_maven_artifacts_generated_report():
    # To ensure we are using the global variables 
    global maven_artifacts, GENISIS_BUILD_JOB
    maven_artifacts_report_file_name = GENISIS_BUILD_JOB + '_current_maven_artifacts_report'
    print ''
    print ''
    print ''
    print 'Create ' + maven_artifacts_report_file_name
    print ''

    new_maven_artifacts_report_file = create_new_report_file(maven_artifacts_report_file_name)
    print_and_write(new_maven_artifacts_report_file, center_header(' Root build job "' + GENISIS_BUILD_JOB + '" ', '+'))
    print_and_write(new_maven_artifacts_report_file, center_header(' Jenkins Maven jobs that create Artifacts ','+'))
    print_and_write(new_maven_artifacts_report_file, center_header(' Note: Not in build order ','+'))

    vce_artifacts_created = 0
    for jenkins_job, artifact_dict in maven_artifacts.iteritems():
        print_and_write(new_maven_artifacts_report_file, jenkins_job)
        artifacts = artifact_dict['artifacts']
        for artifact in artifacts:
            vce_artifacts_created += 1
            artifact_id      = artifact[0]
            artifact_version = artifact[1]
            artifact_type    = artifact[2]
            artifact_group   = artifact[3]
            # Print the information in columns to make it easier to read.
            print_and_write(new_maven_artifacts_report_file, ' ' * 10 + artifact_group + ' ' * (38 - len(artifact_group)) + artifact_id + ' ' * (34 - len(artifact_id)) + artifact_version + ' ' * (20 - len(artifact_version)) + artifact_type)
            # Add the mapping dictionary to make lookup easier later
            artifact_to_job_mapping.update({artifact[0]:jenkins_job})
    print_and_write(new_maven_artifacts_report_file, '')
    print_and_write(new_maven_artifacts_report_file, 'Total VCE artifacts created = ' + str(vce_artifacts_created))
    new_maven_artifacts_report_file.close()

    file_differences = compare_new_and_existing_reports(maven_artifacts_report_file_name)

    maven_artifacts_html_file_name = maven_artifacts_report_file_name + '.html'

    # Create/Recreate the HTML file if there are differences or the file cannot be found
    if file_differences or not os.path.isfile(maven_artifacts_html_file_name):
        if os.path.isfile(maven_artifacts_html_file_name):
            os.remove(maven_artifacts_html_file_name)
        maven_artifacts_html_file = open(maven_artifacts_html_file_name, 'w')
        title_text = GENISIS_BUILD_JOB + ' VCE Created Artifacts'
        create_html_list_header(maven_artifacts_html_file, title_text)
        maven_artifacts_html_file.write('  <table class="sortable" border=1>\n')
        maven_artifacts_html_file.write('    <thead>\n')
        maven_artifacts_html_file.write('      <tr style="color: black; background: lightgray;">\n')
        maven_artifacts_html_file.write('        <th>Jenkins Jobs</th>\n')
        maven_artifacts_html_file.write('        <th>Artifact ID</th>\n')
        maven_artifacts_html_file.write('        <th>Artifact Version</th>\n')
        maven_artifacts_html_file.write('        <th>Artifact Group</th>\n')
        maven_artifacts_html_file.write('        <th>Artifact Type</th>\n')
        maven_artifacts_html_file.write('      </tr>\n')
        maven_artifacts_html_file.write('    </thead>\n')
        maven_artifacts_html_file.write('    <tbody>\n')

        for jenkins_job, artifact_dict in maven_artifacts.iteritems():
            artifacts = artifact_dict['artifacts']
            for artifact in artifacts:
                artifact_id      = artifact[0]
                artifact_version = artifact[1]
                artifact_type    = artifact[2]
                artifact_group   = artifact[3]
                artifactory_path = artifact_group.replace('.','/') + '/' + artifact_id + '/' + artifact_version + '/' + artifact_id + '-' + artifact_version + '.' + artifact_type
#                 TEST_ARTIFACTORY_URL = VCE_ARTIFACTORY_REPOSITORY +  'com/vce/common-crawler/3.1.0.0/common-crawler-3.1.0.0.jar'
                maven_artifacts_html_file.write('      <tr>\n')
                maven_artifacts_html_file.write('        <td><a href="' + JENKINS_JOBS + jenkins_job + '">' + jenkins_job + '</a>\n')
                maven_artifacts_html_file.write('        <td><a href="'+ VCE_ARTIFACTORY_REPOSITORY + artifactory_path + '">'+artifact_id+'</td>\n')
#                 maven_artifacts_html_file.write('        <td>'+artifact_id+'</td>\n')
                maven_artifacts_html_file.write('        <td>'+artifact_version+'</td>\n')
                maven_artifacts_html_file.write('        <td>'+artifact_group+'</td>\n')
                maven_artifacts_html_file.write('        <td>'+artifact_type+'</td>\n')
                maven_artifacts_html_file.write('      </tr>\n')
        maven_artifacts_html_file.write('    </tbody>\n')
        maven_artifacts_html_file.write('    <tfoot>\n')
        maven_artifacts_html_file.write('      <tr>\n')
        maven_artifacts_html_file.write('        <td colspan="5">Total VCE Artifacts Created = ' + str(vce_artifacts_created) + '</td>\n')
        maven_artifacts_html_file.write('      </tr>\n')
        maven_artifacts_html_file.write('    </tfoot>\n')
        maven_artifacts_html_file.write('  </table>\n')
        create_html_end_of_report(maven_artifacts_html_file)
        maven_artifacts_html_file.close()
    return file_differences


def create_jenkins_artifacts_preserved_report():
    # To ensure we are using the global variables 
    global jenkins_artifacts, GENISIS_BUILD_JOB
    jenkins_artifacts_report_file_name = GENISIS_BUILD_JOB + '_jenkins_artifacts_preserved_report'
    print ''
    print ''
    print ''
    print 'Create ' + jenkins_artifacts_report_file_name
    print ''

    new_jenkins_artifacts_report_file = create_new_report_file(jenkins_artifacts_report_file_name)
    print_and_write(new_jenkins_artifacts_report_file, center_header(' Root build job "' + GENISIS_BUILD_JOB + '" ', '+'))
    print_and_write(new_jenkins_artifacts_report_file, center_header(' Jenkins Preserved Artifacts ','+'))
    print_and_write(new_jenkins_artifacts_report_file, center_header(' Note: Not in build order ','+'))

    jenkins_artifacts_preserved = 0
    for jenkins_job, artifacts in jenkins_artifacts.iteritems():
        print_and_write(new_jenkins_artifacts_report_file, jenkins_job)
        for artifact in artifacts:
            jenkins_artifacts_preserved += 1
            display_path = artifact['displayPath']
            if not display_path:
                display_path = 'N/A'
            print_and_write(new_jenkins_artifacts_report_file, ' ' * 10 + artifact['fileName'] + ' ' * (45 - len(artifact['fileName'])) + display_path + ' ' * (45 - len(display_path)) + artifact['relativePath'])

    print_and_write(new_jenkins_artifacts_report_file, '')
    new_jenkins_artifacts_report_file.close()

    file_differences = compare_new_and_existing_reports(jenkins_artifacts_report_file_name)

    jenkins_artifacts_html_file_name = jenkins_artifacts_report_file_name + '.html'

    # Create/Recreate the HTML file if there are differences or the file cannot be found
    if file_differences or not os.path.isfile(jenkins_artifacts_html_file_name):

        if os.path.isfile(jenkins_artifacts_html_file_name):
            os.remove(jenkins_artifacts_html_file_name)
        jenkins_artifacts_html_file = open(jenkins_artifacts_html_file_name, 'w')
        title_text = GENISIS_BUILD_JOB + ' Jenkins Preserved Artifacts'
        create_html_list_header(jenkins_artifacts_html_file, title_text)
        jenkins_artifacts_html_file.write('  <table class="sortable" border=1>\n')
        jenkins_artifacts_html_file.write('    <thead>\n')
        jenkins_artifacts_html_file.write('      <tr style="color: black; background: lightgray;">\n')
        jenkins_artifacts_html_file.write('        <th>Jenkins Jobs</th>\n')
        jenkins_artifacts_html_file.write('        <th>Artifact File Name</th>\n')
        jenkins_artifacts_html_file.write('        <th>Jenkins Display Path</th>\n')
        jenkins_artifacts_html_file.write('        <th>Jenkins Workspace Relative Path</th>\n')
        jenkins_artifacts_html_file.write('      </tr>\n')
        jenkins_artifacts_html_file.write('    </thead>\n')
        jenkins_artifacts_html_file.write('    <tbody>\n')

        for jenkins_job, artifacts in jenkins_artifacts.iteritems():
            for artifact in artifacts:
                display_path = artifact['displayPath']
                if not display_path:
                    display_path = '.N/A'
                jenkins_artifacts_html_file.write('      <tr>\n')
                jenkins_artifacts_html_file.write('        <td><a href="' + JENKINS_JOBS + jenkins_job + '">' + jenkins_job + '</a>\n')
                jenkins_artifacts_html_file.write('        <td>' + artifact['fileName'] + '</td>\n')
                jenkins_artifacts_html_file.write('        <td>' + display_path + '</td>\n')
                jenkins_artifacts_html_file.write('        <td>' + artifact['relativePath'] + '</td>\n')
                jenkins_artifacts_html_file.write('      </tr>\n')
        jenkins_artifacts_html_file.write('    </tbody>\n')
        jenkins_artifacts_html_file.write('    <tfoot>\n')
        jenkins_artifacts_html_file.write('      <tr>\n')
        jenkins_artifacts_html_file.write('        <td colspan="5">Total Jenkins Artifacts Preserved = ' + str(jenkins_artifacts_preserved) + '</td>\n')
        jenkins_artifacts_html_file.write('      </tr>\n')
        jenkins_artifacts_html_file.write('    </tfoot>\n')
        jenkins_artifacts_html_file.write('  </table>\n')
        create_html_end_of_report(jenkins_artifacts_html_file)
        jenkins_artifacts_html_file.close()
    return file_differences


def create_all_maven_dependencies_report():
    # To ensure we are using the global variables 
    global maven_artifacts, GENISIS_BUILD_JOB
    all_maven_dependencies_report_file_name = GENISIS_BUILD_JOB + '_all_maven_dependencies_report'
    print ''
    print ''
    print ''
    print 'Create ' + all_maven_dependencies_report_file_name
    print ''

    all_maven_dependencies_report_file = create_new_report_file(all_maven_dependencies_report_file_name)
    print_and_write(all_maven_dependencies_report_file, center_header(' Root build job "' + GENISIS_BUILD_JOB + '" ', '='))
    print_and_write(all_maven_dependencies_report_file, center_header(' All Maven Dependencies ','='))
    print_and_write(all_maven_dependencies_report_file, center_header(' Note: Not in build order ','='))

    for jenkins_job, job_info_dict in maven_artifacts.iteritems():
        print_and_write(all_maven_dependencies_report_file, jenkins_job)
        dependencies = job_info_dict['dependencies']
        for dependency in dependencies:
            dependency_group   = dependency[0]
            dependency_id      = dependency[1]
            dependency_version = dependency[2]
            # Print the information in columns to make it easier to read.
            print_and_write(all_maven_dependencies_report_file, ' ' * 10 + dependency_group + ' ' * (38 - len(dependency_group)) + dependency_id + ' ' * (52 - len(dependency_id)) + dependency_version)
    all_maven_dependencies_report_file.close()

    file_differences = compare_new_and_existing_reports(all_maven_dependencies_report_file_name)

    all_maven_dependencies_html_file_name = all_maven_dependencies_report_file_name + '.html'

    # Create/Recreate the HTML file if there are differences or the file cannot be found
    if file_differences or not os.path.isfile(all_maven_dependencies_html_file_name):
        
        if os.path.isfile(all_maven_dependencies_html_file_name):
            os.remove(all_maven_dependencies_html_file_name)
        all_maven_dependencies_html_file = open(all_maven_dependencies_html_file_name, 'w')
        title_text = GENISIS_BUILD_JOB + ' Maven Dependencies'
        create_html_list_header(all_maven_dependencies_html_file, title_text)
        all_maven_dependencies_html_file.write('  <table class="sortable" border=1>\n')
        all_maven_dependencies_html_file.write('    <thead>\n')
        all_maven_dependencies_html_file.write('      <tr style="color: black; background: lightgray;">\n')
        all_maven_dependencies_html_file.write('        <th>Jenkins Jobs</th>\n')
        all_maven_dependencies_html_file.write('        <th>Artifact ID</th>\n')
        all_maven_dependencies_html_file.write('        <th>Artifact Version</th>\n')
        all_maven_dependencies_html_file.write('        <th>Artifact Group</th>\n')
        all_maven_dependencies_html_file.write('      </tr>\n')
        all_maven_dependencies_html_file.write('    </thead>\n')
        all_maven_dependencies_html_file.write('    <tbody>\n')

        for jenkins_job, artifact_dict in maven_artifacts.iteritems():
            dependencies = artifact_dict['dependencies']
            for dependency in dependencies:
                dependency_group      = dependency[0]
                dependency_id         = dependency[1]
                dependency_version    = dependency[2]
                ARTIFACTORY_REPOSITORY=CACHED_ARTIFACTORY_REPOSITORY
                if 'vce' in dependency_group:
                    ARTIFACTORY_REPOSITORY=VCE_ARTIFACTORY_REPOSITORY
                dependency_path = dependency_group.replace('.','/') + '/' + dependency_id + '/' + dependency_version

                all_maven_dependencies_html_file.write('      <tr>\n')
                all_maven_dependencies_html_file.write('        <td><a href="' + JENKINS_JOBS + jenkins_job + '">' + jenkins_job + '</a>\n')
                all_maven_dependencies_html_file.write('        <td><a href="'+ ARTIFACTORY_REPOSITORY + dependency_path + '">'+dependency_id+'</td>\n')
                all_maven_dependencies_html_file.write('        <td>'+dependency_version+'</td>\n')
                all_maven_dependencies_html_file.write('        <td>'+dependency_group+'</td>\n')
                all_maven_dependencies_html_file.write('      </tr>\n')
        all_maven_dependencies_html_file.write('    </tbody>\n')
        all_maven_dependencies_html_file.write('  </table>\n')
        create_html_end_of_report(all_maven_dependencies_html_file)
        all_maven_dependencies_html_file.close()
    return file_differences


def create_dependency_report():
    # To ensure we are using the global variables 
    global artifact_to_job_mapping, build_order, build_order_discrepancy, copy_jobs, manual_dependencies, maven_artifacts, prebuild_maven_jobs, GENISIS_BUILD_JOB

    job_to_dependency_mapping = {}

    dependency_report_file_name = GENISIS_BUILD_JOB + '_dependency_report'
    print ''
    print ''
    print ''
    print 'Create ' + dependency_report_file_name
    print ''

    new_dependency_report_file = create_new_report_file(dependency_report_file_name)
    print_and_write(new_dependency_report_file, center_header(' Root build job "' + GENISIS_BUILD_JOB + '" ', '#'))
    print_and_write(new_dependency_report_file, center_header(' VCE dependencies computed by ' + os.path.basename(sys.argv[0]) + ' ','#'))

    # Always skip the first job in the build order as it is the genesis job
    for build_job in build_order[1:]:
        # Dictionary to hold the complete of dependencies.
        job_dependency_dict = {}

        # Build job is a list with the name and the build order
        build_job_name = build_job[0]
        build_job_order = build_job[1].strip()
        # Leave a comment in the dependency file to highlight the build order
        print_and_write(new_dependency_report_file, '# ' + build_job_order + ' ' + build_job_name)

        # From the copy_jobs dictionary get the copy jobs list that matches the current job name.
        copy_job_dependencies = copy_jobs.get(build_job_name,'')
        # Loop through and add all of the jobs from which this job copies Jenkins artifacts
        for copy_from_job_dependency_list in copy_job_dependencies:
            copy_from_job_name = copy_from_job_dependency_list[0]
            copy_from_job_filter = copy_from_job_dependency_list[1]
            copy_from_job_target = copy_from_job_dependency_list[2]
            # First add the copy job to the job_dependency_dict
            job_dependency_dict[copy_from_job_name]=''
            # It's possible to copy from a job that is not part of the current build
            # Test for that here
            if build_order_dict_by_name.get(copy_from_job_name, ''):
                copy_from_job_build_order = build_order_dict_by_name.get(copy_from_job_name).strip()
                if build_job_order < copy_from_job_build_order:
                    # Add to the buld_order discrepancy list
                    build_order_discrepancy.append([build_job_name, 'copy', build_job_order, copy_from_job_name, copy_from_job_build_order, copy_from_job_filter, copy_from_job_target])
            else:
                updated_copy_from_job_list = []
                updated_copy_from_job_list.append(copy_from_job_dependency_list)
                # In case there are multiple copy jobs indexed by this single build job
                if out_of_build_copy_dict.get(build_job_name, ''):
                    for copy_info in out_of_build_copy_dict.get(build_job_name):
                        updated_copy_from_job_list.append(copy_info)
                out_of_build_copy_dict[build_job_name]=updated_copy_from_job_list

        # This is a comma separated list of dependencies
        manual_job_dependencies_string = manual_dependencies.get(build_job_name, '')
        # If the build_job_name exists in the manual_dependencies dictionary.
        if manual_job_dependencies_string:
            manual_job_dependencies_list = manual_job_dependencies_string.split(',')

            # Loop through all of the jobs and add the dependencies
            for manual_job_dependency in manual_job_dependencies_list:
                manual_job_dependency = manual_job_dependency.strip()
                # First add the dependency to the job_dependency_dict
                job_dependency_dict[manual_job_dependency]=''
                # Grab the build order of the dependent job
                manual_job_build_order = build_order_dict_by_name.get(manual_job_dependency, '')
                # It is possible to have a manual build dependency that is not part of the current build.
                if manual_job_build_order:
                    manual_job_build_order = manual_job_build_order.strip()
                    # If we find that current build job was built before manually entered dependencies
                    if build_job_order < manual_job_build_order:
                        discrepency_type = 'manual error'
                        if build_job_order == ('.').join(manual_job_build_order.split('.')[:-1]):
                            discrepency_type = 'manual warning'
                            build_order_discrepancy.append([build_job_name, discrepency_type,  build_job_order, manual_job_dependency, manual_job_build_order])
                else:
                    # Add the build job so that it can be reported later.
                    current_out_of_build_job_manual_dependencies_for_job = out_of_build_manual_dependency_dict.get(build_job_name, '')
                    if current_out_of_build_job_manual_dependencies_for_job:
                        updated_out_of_build_job_manual_dependencies_for_job = current_out_of_build_job_manual_dependencies_for_job + ' ' +  manual_job_dependency 
                        out_of_build_manual_dependency_dict[build_job_name]=updated_out_of_build_job_manual_dependencies_for_job
                    else:
                        out_of_build_manual_dependency_dict[build_job_name]=manual_job_dependency

        # From the maven_artifacts dictionary get the maven info list of dictionaries that matches the current job name
        maven_info = maven_artifacts.get(build_job_name,'')
        # Ensure that we are dealing with a job that has an entry in the maven_artifacts dictionary
        if maven_info and not 'parent' in build_job_name:
            # Get the vce_dependencies list of lists from the maven_info dictionary
            vce_dependencies = maven_info.get('vce_dependencies')
            # Loop through each entry
            for vce_dependency_list in vce_dependencies:
                vce_dependency_groupId    = vce_dependency_list[0]
                vce_dependency_artifactId = vce_dependency_list[1]
                vce_dependency_version    = vce_dependency_list[2]
                vce_dependency_string     = vce_dependency_groupId + '.' + vce_dependency_artifactId
                if vce_dependency_version:
                    vce_dependency_string = vce_dependency_string + '.' + vce_dependency_version
                # It is possible to have a dependency that is outside of this current build.
                # Test for that here 
                if artifact_to_job_mapping.get(vce_dependency_artifactId):
                    jenkins_job_that_creates_artifact = artifact_to_job_mapping.get(vce_dependency_artifactId)
                    # Use a dictionary to automatically remove duplicates
                    job_dependency_dict[jenkins_job_that_creates_artifact]=''
                    # Compare the build order to the dependent build orders
                    dependent_build_order = build_order_dict_by_name.get(jenkins_job_that_creates_artifact).strip()
                    if build_job_order < dependent_build_order:
                        build_order_discrepancy.append([build_job_name, 'maven', build_job_order, jenkins_job_that_creates_artifact, dependent_build_order, vce_dependency_string])
                else:
                    job_out_of_build_vce_dependencies = out_of_build_vce_dependency_dict.get(build_job_name, '')
                    if not job_out_of_build_vce_dependencies:
                        # If there is not an existing entry create an empty dictionary
                        job_out_of_build_vce_dependencies = {}
                    job_out_of_build_vce_dependencies[vce_dependency_string]=[vce_dependency_groupId, vce_dependency_artifactId, vce_dependency_version]
                    # Replace the current build_job_name entry with the updated content
                    out_of_build_vce_dependency_dict[build_job_name]=job_out_of_build_vce_dependencies

        # Create an empty string to start
        dependency_string = ''
        # Sort all of the keys from the dictionary
        dependency_list = sorted(job_dependency_dict.keys())
        for dependent_job in dependency_list:
            if not build_job_name == dependent_job:
                dependency_string = dependency_string + dependent_job + ', '
        # If the dependency string is not blank remove the last 2 characters
        if dependency_string:
            dependency_string = dependency_string[:-2]
        #print the resulting dependency string
        print_and_write(new_dependency_report_file, build_job_name + ':' + dependency_string)
        job_to_dependency_mapping[build_job_name]=dependency_string
    new_dependency_report_file.close()

    file_differences = compare_new_and_existing_reports(dependency_report_file_name)

    dependency_report_html_file_name = dependency_report_file_name + '.html'

    # Create/Recreate the HTML file if there are differences or the file cannot be found
    if file_differences or not os.path.isfile(dependency_report_html_file_name):

        if os.path.isfile(dependency_report_html_file_name):
            os.remove(dependency_report_html_file_name)
        dependency_report_html_file = open(dependency_report_html_file_name, 'w')
        title_text = GENISIS_BUILD_JOB + ' Build Dependencies'
        create_html_list_header(dependency_report_html_file, title_text)
        dependency_report_html_file.write('  <table class="sortable" border=1>\n')
        dependency_report_html_file.write('    <thead>\n')
        dependency_report_html_file.write('      <tr style="color: black; background: lightgray;">\n')
        dependency_report_html_file.write('        <th>Jenkins Build Job</th>\n')
        dependency_report_html_file.write('        <th>Dependent Jobs</th>\n')
        dependency_report_html_file.write('      </tr>\n')
        dependency_report_html_file.write('    </thead>\n')
        dependency_report_html_file.write('    <tbody>\n')
        for build_job in build_order[1:]:
            build_job_name = build_job[0]
            dependent_job_link_string = ''
            dependent_jobs_string = job_to_dependency_mapping.get(build_job_name)
            for job in dependent_jobs_string.split(','):
                dependent_job_link_string += '<a href="' + JENKINS_JOBS + job.strip() + '">' + job.strip() + ',&nbsp;'
            dependent_job_link_string = dependent_job_link_string[:-7]
            dependency_report_html_file.write('      <tr>\n')
            dependency_report_html_file.write('        <td><a href="' + JENKINS_JOBS + build_job_name+'">' + build_job_name + '</td>\n')
            dependency_report_html_file.write('        <td>'+dependent_job_link_string+'</td>\n')
#             dependency_report_html_file.write('        <td><a href="' + JENKINS_JOBS + build[0] + '">' + build[0] + '</a>\n') 
            dependency_report_html_file.write('      </tr>\n')
        dependency_report_html_file.write('    </tbody>\n')
        dependency_report_html_file.write('    <tfoot>\n')
        dependency_report_html_file.write('      <tr>\n')
        dependency_report_html_file.write('<td>Total build jobs</td>\n')
        dependency_report_html_file.write('        <td>'+str(len(build_order))+'</td>\n')
        dependency_report_html_file.write('      </tr>\n')
        dependency_report_html_file.write('    </tfoot>\n')
        dependency_report_html_file.write('  </table>\n')
        create_html_end_of_report(dependency_report_html_file)
        dependency_report_html_file.close()
    return file_differences


def create_out_of_build_maven_vce_dependency_report():
    maven_vce_dependencies_not_in_build_report_file_name = GENISIS_BUILD_JOB + '_maven_vce_dependencies_not_in_build_report'
    print ''
    print ''
    print ''
    print 'Create ' + maven_vce_dependencies_not_in_build_report_file_name
    print ''

    new_maven_vce_dependencies_not_in_build_report_file = create_new_report_file(maven_vce_dependencies_not_in_build_report_file_name)
    print_and_write(new_maven_vce_dependencies_not_in_build_report_file, center_header(' Root build job "' + GENISIS_BUILD_JOB + '" ', '$'))
    print_and_write(new_maven_vce_dependencies_not_in_build_report_file, center_header(' Maven vce dependencies not in build computed by ' + os.path.basename(sys.argv[0]) + ' ','$'))
    print_and_write(new_maven_vce_dependencies_not_in_build_report_file, '')
    jobs_with_out_of_build_maven_vce_dependencies = sorted(out_of_build_vce_dependency_dict.keys())
    for job in jobs_with_out_of_build_maven_vce_dependencies:
        print_and_write(new_maven_vce_dependencies_not_in_build_report_file, job)
        artifact_string = ''
        out_of_build_vce_artifacts = out_of_build_vce_dependency_dict.get(job)
        artifacts = sorted(out_of_build_vce_artifacts.keys())
        for artifact in artifacts:
            artifact_string = artifact_string + artifact + ' ' * (55 - len(artifact))
        print_and_write(new_maven_vce_dependencies_not_in_build_report_file, ' ' * 20  + artifact_string)

    new_maven_vce_dependencies_not_in_build_report_file.close()

    file_differences = compare_new_and_existing_reports(maven_vce_dependencies_not_in_build_report_file_name)

    maven_vce_dependencies_not_in_build_html_file_name = maven_vce_dependencies_not_in_build_report_file_name + '.html'

    # Create/Recreate the HTML file if there are differences or the file cannot be found
    if file_differences or not os.path.isfile(maven_vce_dependencies_not_in_build_html_file_name):

        if os.path.isfile(maven_vce_dependencies_not_in_build_html_file_name):
            os.remove(maven_vce_dependencies_not_in_build_html_file_name)
        maven_vce_dependencies_not_in_build_html_file = open(maven_vce_dependencies_not_in_build_html_file_name, 'w')
        title_text = GENISIS_BUILD_JOB + ' Maven VCE Dependencies Not Part of Build '
        create_html_list_header(maven_vce_dependencies_not_in_build_html_file, title_text)
        maven_vce_dependencies_not_in_build_html_file.write('  <table class="sortable" border=1>\n')
        maven_vce_dependencies_not_in_build_html_file.write('    <thead>\n')
        maven_vce_dependencies_not_in_build_html_file.write('      <tr style="color: black; background: lightgray;">\n')
        maven_vce_dependencies_not_in_build_html_file.write('        <th>Jenkins Jobs</th>\n')
        maven_vce_dependencies_not_in_build_html_file.write('        <th>Out of build VCE Artifacts</th>\n')
        maven_vce_dependencies_not_in_build_html_file.write('      </tr>\n')
        maven_vce_dependencies_not_in_build_html_file.write('    </thead>\n')
        maven_vce_dependencies_not_in_build_html_file.write('    <tbody>\n')
        for job in jobs_with_out_of_build_maven_vce_dependencies:
            artifact_string = ''
            out_of_build_vce_artifacts = out_of_build_vce_dependency_dict.get(job)
            artifacts = sorted(out_of_build_vce_artifacts.keys())
            for artifact in artifacts:
                artifact_list = out_of_build_vce_artifacts.get(artifact)
                artifact_group   = artifact_list[0]
                artifact_id      = artifact_list[1]
                artifact_version = artifact_list[2]
                artifactory_path = artifact_group.replace('.','/') + '/' + artifact_id + '/' + artifact_version
                artifact_string += '<a href="' + VCE_ARTIFACTORY_REPOSITORY + artifactory_path + '">' + artifact + ',&nbsp;'
            artifact_string = artifact_string[:-7]
            maven_vce_dependencies_not_in_build_html_file.write('      <tr>\n')
            maven_vce_dependencies_not_in_build_html_file.write('        <td><a href="' + JENKINS_JOBS + job + '">' + job + '</a>\n')
            maven_vce_dependencies_not_in_build_html_file.write('        <td>'+ artifact_string + '</td>\n')
        maven_vce_dependencies_not_in_build_html_file.write('    </tbody>\n')
        maven_vce_dependencies_not_in_build_html_file.write('  </table>\n')
        create_html_end_of_report(maven_vce_dependencies_not_in_build_html_file)
        maven_vce_dependencies_not_in_build_html_file.close()
    return file_differences


def create_build_discrepancies_report():
    index = '  '
    discrepency_num=1
    discrepancy_job = ''

    build_discrepancies_report_file_name = GENISIS_BUILD_JOB + '_build_discrepancies_report'    
    print ''
    print ''
    print 'Create ' + build_discrepancies_report_file_name
    print ''

    new_build_discrepancies_report_file = create_new_report_file(build_discrepancies_report_file_name)
    print_and_write(new_build_discrepancies_report_file, center_header(' Root build job "' + GENISIS_BUILD_JOB + '" ', '&'))
    print_and_write(new_build_discrepancies_report_file, center_header(' VCE build discrepancies computed by ' + os.path.basename(sys.argv[0]) + ' ','&'))

    for discrepancy_list in build_order_discrepancy:
        # Pull the information from the list and put it into more readable variable name
        discrepancy_type          = discrepancy_list[1]
        discrepancy_job_order     = discrepancy_list[2]
        dependent_job             = discrepancy_list[3]
        dependent_job_build_order = discrepancy_list[4]

        if discrepancy_job != discrepancy_list[0]:
            print_and_write(new_build_discrepancies_report_file, '')
            print_and_write(new_build_discrepancies_report_file, discrepancy_list[0] + ' built @ step ' + discrepancy_job_order)
            discrepency_num=1
        else:
            discrepency_num += 1
        # Update the discrepency_job variable to enable the change of the header once the job changes.
        discrepancy_job = discrepancy_list[0]

        if discrepancy_type == 'copy':
            # Pull the additional information from the list
            copy_from_job_filter = discrepancy_list[5]
#             copy_from_job_target = discrepancy_list[6]

            print_and_write(new_build_discrepancies_report_file, index + str(discrepency_num)            + ' Jenkins copy dependency. Copying artifact(s) "' + copy_from_job_filter + '"')
            print_and_write(new_build_discrepancies_report_file, index + ' ' * len(str(discrepency_num)) + ' from job ' + dependent_job + ' which is run at build step ' + dependent_job_build_order)
        elif discrepancy_type == 'maven':
            # Pull the additional information from the list
            dependent_artifact = discrepancy_list[5]

            print_and_write(new_build_discrepancies_report_file, index + str(discrepency_num)            + ' Maven dependency on artifact ' + dependent_artifact)
            print_and_write(new_build_discrepancies_report_file, index + ' ' * len(str(discrepency_num)) + ' created in job ' + dependent_job + ' in build step ' + dependent_job_build_order)
        elif 'manual' in discrepancy_type:
            print_and_write(new_build_discrepancies_report_file, index + str(discrepency_num)            + ' Incorrect manual dependency introduced ')
            print_and_write(new_build_discrepancies_report_file, index + ' ' * len(str(discrepency_num)) + ' Manual dependency on job ' + dependent_job + ' run at build step ' + dependent_job_build_order)
        else:
            print_and_write(new_build_discrepancies_report_file, 'Unknown discrepancy type')
            print_and_write(new_build_discrepancies_report_file, str(discrepancy_list))
    new_build_discrepancies_report_file.close()

    file_differences = compare_new_and_existing_reports(build_discrepancies_report_file_name)

    build_discrepancies_html_file_name = build_discrepancies_report_file_name + '.html'

    # Create/Recreate the HTML file if there are differences or the file cannot be found
    if file_differences or not os.path.isfile(build_discrepancies_html_file_name):

        if os.path.isfile(build_discrepancies_html_file_name):
            os.remove(build_discrepancies_html_file_name)
        build_discrepancies_html_file = open(build_discrepancies_html_file_name, 'w')
        title_text = GENISIS_BUILD_JOB + ' Build Discrepencies'
        create_html_list_header(build_discrepancies_html_file, title_text)
        build_discrepancies_html_file.write('  <table class="sortable" border=1>\n')
        build_discrepancies_html_file.write('    <thead>\n')
        build_discrepancies_html_file.write('      <tr style="color: black; background: lightgray;">\n')
        build_discrepancies_html_file.write('        <th>Dependent Build Job</th>\n')
        build_discrepancies_html_file.write('        <th>Dependent Build Step</th>\n')
        build_discrepancies_html_file.write('        <th>Dependency Type</th>\n')
        build_discrepancies_html_file.write('        <th>Dependency Job</th>\n')
        build_discrepancies_html_file.write('        <th>Dependency Job Build Step</th>\n')
        build_discrepancies_html_file.write('      </tr>\n')
        build_discrepancies_html_file.write('    </thead>\n')
        build_discrepancies_html_file.write('    <tbody>\n')
        for discrepancy_list in build_order_discrepancy:
            # Pull the information from the list and put it into more readable variable name
            dependent_job              = discrepancy_list[0]
            dependency_type            = discrepancy_list[1]
            dependent_build_step       = discrepancy_list[2]
            dependency_job             = discrepancy_list[3]
            dependency_job_build_order = discrepancy_list[4]
            build_discrepancies_html_file.write('      <tr>\n')
            build_discrepancies_html_file.write('        <td><a href="' + JENKINS_JOBS + dependent_job+'">' + dependent_job + '</td>\n')
            build_discrepancies_html_file.write('        <td>'+dependent_build_step+'</td>\n')
            build_discrepancies_html_file.write('        <td>'+dependency_type+'</td>\n')
            build_discrepancies_html_file.write('        <td><a href="' + JENKINS_JOBS + dependency_job+'">' + dependency_job + '</td>\n')
            build_discrepancies_html_file.write('        <td>'+dependency_job_build_order+'</td>\n')
            build_discrepancies_html_file.write('      </tr>\n')
        build_discrepancies_html_file.write('    </tbody>\n')
        build_discrepancies_html_file.write('  </table>\n')
        create_html_end_of_report(build_discrepancies_html_file)
        build_discrepancies_html_file.close()
    return file_differences


def create_out_of_build_copy_report():
    copy_jobs_not_in_build_report_file_name = GENISIS_BUILD_JOB + '_copy_jobs_not_in_build_report'
    print ''
    print ''
    print ''
    print 'Create ' + copy_jobs_not_in_build_report_file_name
    print ''
    new_copy_jobs_not_in_build_report_file = create_new_report_file(copy_jobs_not_in_build_report_file_name)
    print_and_write(new_copy_jobs_not_in_build_report_file, center_header(' Root build job "' + GENISIS_BUILD_JOB + '" ', '%'))
    print_and_write(new_copy_jobs_not_in_build_report_file, center_header(' Copy jobs not in build computed by ' + os.path.basename(sys.argv[0]) + ' ','%'))
    print_and_write(new_copy_jobs_not_in_build_report_file, '')
    jobs_with_out_of_build_copies = sorted(out_of_build_copy_dict.keys())
    for job_with_out_of_build_copy in jobs_with_out_of_build_copies:
        print_and_write(new_copy_jobs_not_in_build_report_file, job_with_out_of_build_copy)
        out_of_build_copy_jobs_info = out_of_build_copy_dict.get(job_with_out_of_build_copy)
        out_of_build_copy_jobs_info.sort()
        for copy_job_info in out_of_build_copy_jobs_info:
            copy_from_job    = copy_job_info[0]
            copy_from_filter = copy_job_info[1]
            copy_from_target = copy_job_info[2]
            print_and_write(new_copy_jobs_not_in_build_report_file, ' ' * 30 + copy_from_job + ' ' * (43 - len(copy_from_job)) + copy_from_filter + ' ' * (30 - len(copy_from_filter)) + copy_from_target)

    new_copy_jobs_not_in_build_report_file.close()

    file_differences = compare_new_and_existing_reports(copy_jobs_not_in_build_report_file_name)

    copy_jobs_not_in_build_html_file_name = copy_jobs_not_in_build_report_file_name + '.html'

    # Create/Recreate the HTML file if there are differences or the file cannot be found
    if file_differences or not os.path.isfile(copy_jobs_not_in_build_html_file_name):

        if os.path.isfile(copy_jobs_not_in_build_html_file_name):
            os.remove(copy_jobs_not_in_build_html_file_name)
        copy_jobs_not_in_build_html_file = open(copy_jobs_not_in_build_html_file_name, 'w')
        title_text = GENISIS_BUILD_JOB + ' Copy Jobs Not in Current Build'
        create_html_list_header(copy_jobs_not_in_build_html_file, title_text)
        copy_jobs_not_in_build_html_file.write('  <table class="sortable" border=1>\n')
        copy_jobs_not_in_build_html_file.write('    <thead>\n')
        copy_jobs_not_in_build_html_file.write('      <tr style="color: black; background: lightgray;">\n')
        copy_jobs_not_in_build_html_file.write('        <th>Jenkins Jobs</th>\n')
        copy_jobs_not_in_build_html_file.write('        <th>Copy From Job Not Part of Current Build</th>\n')
        copy_jobs_not_in_build_html_file.write('        <th>Artifact Filter</th>\n')
        copy_jobs_not_in_build_html_file.write('        <th>Target Directory</th>\n')
        copy_jobs_not_in_build_html_file.write('      </tr>\n')
        copy_jobs_not_in_build_html_file.write('    </thead>\n')
        copy_jobs_not_in_build_html_file.write('    <tbody>\n')
        for job_with_out_of_build_copy in jobs_with_out_of_build_copies:
            out_of_build_copy_jobs_info = out_of_build_copy_dict.get(job_with_out_of_build_copy)
            out_of_build_copy_jobs_info.sort()
            for copy_job_info in out_of_build_copy_jobs_info:
                copy_from_job    = copy_job_info[0]
                copy_from_filter = copy_job_info[1]
                copy_from_target = copy_job_info[2]
                copy_jobs_not_in_build_html_file.write('      <tr>\n')
                copy_jobs_not_in_build_html_file.write('        <td><a href="' + JENKINS_JOBS + job_with_out_of_build_copy + '">' + job_with_out_of_build_copy + '</a>\n')
                copy_jobs_not_in_build_html_file.write('        <td><a href="' + JENKINS_JOBS + copy_from_job + '">' + copy_from_job + '</a>\n')
                copy_jobs_not_in_build_html_file.write('        <td>'+copy_from_filter+'</td>\n')
                copy_jobs_not_in_build_html_file.write('        <td>'+copy_from_target+'</td>\n')
                copy_jobs_not_in_build_html_file.write('      </tr>\n')
        copy_jobs_not_in_build_html_file.write('    </tbody>\n')
        copy_jobs_not_in_build_html_file.write('  </table>\n')
        create_html_end_of_report(copy_jobs_not_in_build_html_file)
        copy_jobs_not_in_build_html_file.close()
    return file_differences


def create_duplicate_build_jobs_report():
    duplicate_build_jobs_report_file_name = GENISIS_BUILD_JOB + '_duplicate_build_jobs_report'
    print ''
    print ''
    print 'Create ' + duplicate_build_jobs_report_file_name
    print ''

    new_duplicate_build_jobs_report_file = create_new_report_file(duplicate_build_jobs_report_file_name)
    print_and_write(new_duplicate_build_jobs_report_file, center_header(' Root build job "' + GENISIS_BUILD_JOB + '" ', '!'))
    print_and_write(new_duplicate_build_jobs_report_file, center_header(' Duplicate Build Jobs ','!'))
    print_and_write(new_duplicate_build_jobs_report_file, '')
    duplicated_jobs_list = sorted(duplicate_build_jobs.keys())
    for duplicate_job in duplicated_jobs_list:
        print_and_write(new_duplicate_build_jobs_report_file, duplicate_job + ' ' * (30 - len(duplicate_job)) + ' is built in the following builds steps:  ' + duplicate_build_jobs.get(duplicate_job))

    new_duplicate_build_jobs_report_file.close()

    file_differences = compare_new_and_existing_reports(duplicate_build_jobs_report_file_name)
    duplicate_build_jobs_html_file_name = duplicate_build_jobs_report_file_name + '.html'

    # Create/Recreate the HTML file if there are differences or the file cannot be found
    if file_differences or not os.path.isfile(duplicate_build_jobs_html_file_name):

        if os.path.isfile(duplicate_build_jobs_html_file_name):
            os.remove(duplicate_build_jobs_html_file_name)
        duplicate_build_jobs_html_file = open(duplicate_build_jobs_html_file_name, 'w')
        title_text = GENISIS_BUILD_JOB + ' Duplicate Jenkins Build Jobs '
        create_html_list_header(duplicate_build_jobs_html_file, title_text)
        duplicate_build_jobs_html_file.write('  <table class="sortable" border=1>\n')
        duplicate_build_jobs_html_file.write('    <thead>\n')
        duplicate_build_jobs_html_file.write('      <tr style="color: black; background: lightgray;">\n')
        duplicate_build_jobs_html_file.write('        <th>Jenkins Job</th>\n')
        duplicate_build_jobs_html_file.write('        <th>Steps in Which the Job is Executed</th>\n')
        duplicate_build_jobs_html_file.write('      </tr>\n')
        duplicate_build_jobs_html_file.write('    </thead>\n')
        duplicate_build_jobs_html_file.write('    <tbody>\n')
        duplicated_jobs_list = sorted(duplicate_build_jobs.keys())
        for duplicate_job in duplicated_jobs_list:
            duplicate_jobs_string = ''
            duplicate_build_steps = duplicate_build_jobs.get(duplicate_job).split(' ')
            for duplicate_build_step in duplicate_build_steps:
                duplicate_job_name = build_order_dict_by_number.get(duplicate_build_step.strip())
                duplicate_jobs_string += '<a href="' + JENKINS_JOBS + duplicate_job_name + '">' + duplicate_build_step + '</a>&nbsp;'
            duplicate_build_jobs_html_file.write('      <tr>\n')
            duplicate_build_jobs_html_file.write('        <td><a href="' + JENKINS_JOBS + duplicate_job + '">' + duplicate_job + '</a></td>\n')
            duplicate_build_jobs_html_file.write('        <td>' + duplicate_jobs_string + '</td>\n')
            duplicate_build_jobs_html_file.write('      </tr>\n')
        duplicate_build_jobs_html_file.write('    </tbody>\n')
        duplicate_build_jobs_html_file.write('  </table>\n')
        create_html_end_of_report(duplicate_build_jobs_html_file)
        duplicate_build_jobs_html_file.close()
    return file_differences


def create_out_of_build_manual_dependency_report():
    manual_dependencies_not_in_build_report_file_name = GENISIS_BUILD_JOB + '_manual_dependencies_not_in_build_report'
    print ''
    print ''
    print ''
    print 'Create ' + manual_dependencies_not_in_build_report_file_name
    print ''

    new_manual_dependencies_not_in_build_report_file = create_new_report_file(manual_dependencies_not_in_build_report_file_name)
    print_and_write(new_manual_dependencies_not_in_build_report_file, center_header(' Root build job "' + GENISIS_BUILD_JOB + '" ', '^'))
    print_and_write(new_manual_dependencies_not_in_build_report_file, center_header(' Manual dependencies not in build computed by ' + os.path.basename(sys.argv[0]) + ' ','^'))
    print_and_write(new_manual_dependencies_not_in_build_report_file, '')
    jobs_with_out_of_build_manual_dependencies = sorted(out_of_build_manual_dependency_dict.keys())
    for job in jobs_with_out_of_build_manual_dependencies:
        external_jobs_string = ''
        out_of_build_manual_jobs = out_of_build_manual_dependency_dict.get(job)
        for out_of_build_manual_job in out_of_build_manual_jobs.split(' '):
            external_jobs_string += ' ' * (40 - len(out_of_build_manual_job.strip())) + out_of_build_manual_job
        print_and_write(new_manual_dependencies_not_in_build_report_file, job + ' ' * (50 - len(job))  + external_jobs_string)

    new_manual_dependencies_not_in_build_report_file.close()

    file_differences = compare_new_and_existing_reports(manual_dependencies_not_in_build_report_file_name)

    manual_dependencies_not_in_build_html_file_name = manual_dependencies_not_in_build_report_file_name + '.html'

    # Create/Recreate the HTML file if there are differences or the file cannot be found
    if file_differences or not os.path.isfile(manual_dependencies_not_in_build_html_file_name):
        if os.path.isfile(manual_dependencies_not_in_build_html_file_name):
            os.remove(manual_dependencies_not_in_build_html_file_name)
        manual_dependencies_not_in_build_html_file = open(manual_dependencies_not_in_build_html_file_name, 'w')
        title_text = GENISIS_BUILD_JOB + ' Manual Entered Dependencies Not Part of Build '
        create_html_list_header(manual_dependencies_not_in_build_html_file, title_text)
        manual_dependencies_not_in_build_html_file.write('  <table class="sortable" border=1>\n')
        manual_dependencies_not_in_build_html_file.write('    <thead>\n')
        manual_dependencies_not_in_build_html_file.write('      <tr style="color: black; background: lightgray;">\n')
        manual_dependencies_not_in_build_html_file.write('        <th>Jenkins Jobs</th>\n')
        manual_dependencies_not_in_build_html_file.write('        <th>Out of build Manual Dependencies</th>\n')
        manual_dependencies_not_in_build_html_file.write('      </tr>\n')
        manual_dependencies_not_in_build_html_file.write('    </thead>\n')
        manual_dependencies_not_in_build_html_file.write('    <tbody>\n')
        for job in jobs_with_out_of_build_manual_dependencies:
            external_jobs_string = ''
            out_of_build_manual_jobs = out_of_build_manual_dependency_dict.get(job)
            for out_of_build_manual_job in out_of_build_manual_jobs.split(' '):
                external_jobs_string += '<a href="' + JENKINS_JOBS + out_of_build_manual_job + '">' + out_of_build_manual_job + ',&nbsp;'
            external_jobs_string = external_jobs_string[:-7]
            manual_dependencies_not_in_build_html_file.write('      <tr>\n')
            manual_dependencies_not_in_build_html_file.write('        <td><a href="' + JENKINS_JOBS + job + '">' + job + '</a>\n')
            manual_dependencies_not_in_build_html_file.write('        <td>'+ external_jobs_string + '</td>\n')
        manual_dependencies_not_in_build_html_file.write('    </tbody>\n')
        manual_dependencies_not_in_build_html_file.write('  </table>\n')
        create_html_end_of_report(manual_dependencies_not_in_build_html_file)
        manual_dependencies_not_in_build_html_file.close()
    return file_differences


def create_build_jobs_with_maven_version_change_dict_report():
    maven_version_changes_report_file_name = GENISIS_BUILD_JOB + '_maven_version_changes_report'
    print ''
    print ''
    print ''
    print 'Create ' + maven_version_changes_report_file_name
    print ''
    new_maven_version_changes_report_file_name = create_new_report_file(maven_version_changes_report_file_name)
    print_and_write(new_maven_version_changes_report_file_name, center_header(' Root build job "' + GENISIS_BUILD_JOB + '" ', '_'))
    print_and_write(new_maven_version_changes_report_file_name, center_header(' Maven jobs with version change discovered by ' + os.path.basename(sys.argv[0]) + ' ','_'))
    print_and_write(new_maven_version_changes_report_file_name, '')
    build_jobs_with_maven_version_change = sorted(build_jobs_with_maven_version_change_dict.keys())
    for job in build_jobs_with_maven_version_change:
        version_change_info = build_jobs_with_maven_version_change_dict.get(job)
        old_version = version_change_info[0]
        new_version = version_change_info[1]
        print_and_write(new_maven_version_changes_report_file_name, job + ' ' * (40 - len(job)) + old_version + ' ' * (20 - len(old_version)) + new_version)

    new_maven_version_changes_report_file_name.close()

    file_differences = compare_new_and_existing_reports(maven_version_changes_report_file_name)

    maven_version_changes_report_html_file_name = maven_version_changes_report_file_name + '.html'

    # Create/Recreate the HTML file if there are differences or the file cannot be found
    if file_differences or not os.path.isfile(maven_version_changes_report_html_file_name):

        if os.path.isfile(maven_version_changes_report_html_file_name):
            os.remove(maven_version_changes_report_html_file_name)
        maven_version_changes_report_html_file = open(maven_version_changes_report_html_file_name, 'w')
        title_text = GENISIS_BUILD_JOB + ' Maven Jobs That Change the Version'
        create_html_list_header(maven_version_changes_report_html_file, title_text)
        maven_version_changes_report_html_file.write('  <table class="sortable" border=1>\n')
        maven_version_changes_report_html_file.write('    <thead>\n')
        maven_version_changes_report_html_file.write('      <tr style="color: black; background: lightgray;">\n')
        maven_version_changes_report_html_file.write('        <th>Jenkins Jobs</th>\n')
        maven_version_changes_report_html_file.write('        <th>Orignal Version</th>\n')
        maven_version_changes_report_html_file.write('        <th>Changed Version</th>\n')
        maven_version_changes_report_html_file.write('      </tr>\n')
        maven_version_changes_report_html_file.write('    </thead>\n')
        maven_version_changes_report_html_file.write('    <tbody>\n')
        for job in build_jobs_with_maven_version_change:
            version_change_info = build_jobs_with_maven_version_change_dict.get(job)
            old_version = version_change_info[0]
            new_version = version_change_info[1]
            maven_version_changes_report_html_file.write('      <tr>\n')
            maven_version_changes_report_html_file.write('        <td><a href="' + JENKINS_JOBS + job + '">' + job + '</a>\n')
            maven_version_changes_report_html_file.write('        <td>'+old_version+'</td>\n')
            maven_version_changes_report_html_file.write('        <td>'+new_version+'</td>\n')
            maven_version_changes_report_html_file.write('      </tr>\n')
        maven_version_changes_report_html_file.write('    </tbody>\n')
        maven_version_changes_report_html_file.write('  </table>\n')
        create_html_end_of_report(maven_version_changes_report_html_file)
        maven_version_changes_report_html_file.close()
    return file_differences

def read_manual_dependencies_file():
    # To ensure we are using the global variables 
    global DEPENDENCY_JOB, GENISIS_BUILD_JOB, JENKINS_JOBS

    # Create the dependency job from the global name with the last dot extension from the GENISIS file name.
    build_specific_dependency_job = DEPENDENCY_JOB
    build_specific_dependency_job = build_specific_dependency_job + '.' + '.'.join(GENISIS_BUILD_JOB.split('.')[1:])

    # Create the http request to read the MANUAL_DEPENDENCY_FILE
    dependencies_job_url_request = urllib2.Request(JENKINS_JOBS + build_specific_dependency_job + '/ws/' + MANUAL_DEPENDENCY_FILE + '/*view*/')

    # The file doesn't have to exist so try to read the file but continue with a message if it's missing.
    try:
        # In order to use ConfigParser we must place the entries in a section
        dependencies_section = 'dependencies'
        dependencies_string = urllib2.urlopen(dependencies_job_url_request).read()
        # In order to make the string Configparser compliance we must add a section string.
        dependencies_string = '[' + dependencies_section + ']\n' + dependencies_string

        # Place the string in a buffer that ConfigParser and read as a file.
        buf = StringIO.StringIO(dependencies_string)
        manual_dependencies_parser = ConfigParser.SafeConfigParser()
        # Stop config parser from automatically changing elements to lower case
        manual_dependencies_parser.optionxform = str
        manual_dependencies_parser.readfp(buf)
        print 'manual_dependencies_parser = ' + str(manual_dependencies_parser)

        # Make sure we are updating the global dictionary
        global manual_dependencies
        # Put the contents of the dependencies_section into the manual_dependencies dictionary
        manual_dependencies = dict(manual_dependencies_parser.items(dependencies_section))
        print 'Got the manual_dependencies.'
        print 'manual_dependencies = ' + str(manual_dependencies)

    except urllib2.HTTPError:
        print '*** Manual dependency file "' +  MANUAL_DEPENDENCY_FILE + '" does not exist in the'
        print '*** workspace of Jenkins job "' + build_specific_dependency_job + '".'
        print '*** Proceeding without it.'
        print ''


def email_file_differences(report_name, file_differences):
    # Email's only work from the jenkins host
    if SMTP_SERVER and host == JENKINS_HOST and EMAIL_RECEIVER_LIST != '':
        print 'Emailing the differences in report ' + report_name
        msg = MIMEText(file_differences)
        msg['From']    = EMAIL_FROM
        msg['To']      = EMAIL_RECEIVER_LIST
        msg['Subject'] = report_name + ' report differences.'

        s = smtplib.SMTP(SMTP_SERVER)
        s.sendmail(msg['From'], [msg['To']], msg.as_string())
        s.quit()


########################################################
# Start of the main program flow
########################################################


# Need at least two parameters. The name of the genesis build job and a properties file. 
if len(sys.argv) < 3 or len(sys.argv) > 6:
    print 'Length of argument = ' + str(len(sys.argv))
    help_message()

GENISIS_BUILD_JOB = sys.argv[1]
if len(sys.argv) == 4:
    USERID            = sys.argv[2]
    PASSWORD          = sys.argv[3]
else:
    properties_file_name = sys.argv[2]
    print 'current working directory = ' + os.getcwd()
    if not os.path.isfile(properties_file_name):
        print 'Unable to open properties file "' + properties_file_name + '"'
        print ''
        help_message()

    # Usage of the config parser is a bit heavy handed but I didn't want to go through
    # the steps of a manually parsing a file.
    properties_file = open(properties_file_name, 'r')
    properties_string = properties_file.read()
    auth_section = 'authorization'
    properties_string = '[' + auth_section + ']\n' + properties_string
    buf = StringIO.StringIO(properties_string)
    auth_parser = ConfigParser.SafeConfigParser()
    auth_parser.readfp(buf)
    auth_dict = dict(auth_parser.items(auth_section))
    DEBUG=auth_dict.get('debug','')
    SVN_USERID = auth_dict.get('svn_userid', '')
    SVN_PASSWORD = auth_dict.get('svn_password','')
    JENKINS_USERID = auth_dict.get('jenkins_userid', '')
    JENKINS_PASSWORD = auth_dict.get('jenkins_password','')
    GIT_HUB_AUTH_TOKEN=auth_dict.get('git_auth_token','')
    SMTP_SERVER= auth_dict.get('smtp', '')
    if not JENKINS_USERID or not JENKINS_PASSWORD:
        print 'Unable to get userid or password from given password properties file.'
        print ''
        print 'jenkins_userid   = "' + JENKINS_USERID + '"'
        print 'jenkins_password = "' + JENKINS_PASSWORD + '"'
        print ''
        help_message()

    # Get optional information from the password properties file
    if auth_dict.get('jenkins_host', ''):
        JENKINS_HOST = auth_dict.get('jenkins_host')
    if auth_dict.get('email_receiver_list', ''):
        EMAIL_RECEIVER_LIST = auth_dict.get('email_receiver_list')
    if auth_dict.get('email_from', ''):
        EMAIL_FROM=auth_dict.get('email_from')
    if auth_dict.get('email_subject', ''):
        EMAIL_SUBJECT=auth_dict.get('email_subject')
    if auth_dict.get('debug', ''):
        DEBUG=auth_dict.get('debug')
    if DEBUG:
        print '************************** Debugging is turned on *****************************'

# Get the fully qualified domain name of the local host 
host = socket.getfqdn()

try:
    # The environmental Jenkins email receiver list supersedes and property file based list. 
    JENKINS_EMAIL_RECEIVER_LIST = os.environ['EMAIL_RECEIVER_LIST']
    # If the list is not empty use this information
    if JENKINS_EMAIL_RECEIVER_LIST:
        EMAIL_RECEIVER_LIST = JENKINS_EMAIL_RECEIVER_LIST
except KeyError:
    pass

# Email's only work from the jenkins host
if not SMTP_SERVER or host != JENKINS_HOST or not EMAIL_RECEIVER_LIST:
    if host != JENKINS_HOST:
        print '*** Running on host"' + host + '" which is not the Jenkins host.'
    if not SMTP_SERVER:
        print '*** smtp server not set in the properties file.'
    if not EMAIL_RECEIVER_LIST:
        print '*** email_receiver_list not set in the properties file.'
    print '*** Unable to send email notifications of changes.'
    print ''
else:
    # Grab the other booleans used to determine which notifications get sent.
    try:
        SHELL_JOBS_CHANGES_NOTIFICATION = os.environ['SHELL_JOBS_CHANGES_NOTIFICATION']
        if SHELL_JOBS_CHANGES_NOTIFICATION == 'false':
            SHELL_JOBS_CHANGES_NOTIFICATION=''
    except KeyError:
        pass

    try:
        MAVEN_COMPLETE_DEPENDENCIES_CHANGES_NOTIFICATION = os.environ['MAVEN_COMPLETE_DEPENDENCIES_CHANGES_NOTIFICATION']
        if MAVEN_COMPLETE_DEPENDENCIES_CHANGES_NOTIFICATION == 'false':
            MAVEN_COMPLETE_DEPENDENCIES_CHANGES_NOTIFICATION=''
    except KeyError:
        pass

    try:
        MAVEN_ARTIFACTS_GENERATED_CHANGES_NOTIFICATION = os.environ['MAVEN_ARTIFACTS_GENERATED_CHANGES_NOTIFICATION']
        if MAVEN_ARTIFACTS_GENERATED_CHANGES_NOTIFICATION == 'false':
            MAVEN_ARTIFACTS_GENERATED_CHANGES_NOTIFICATION=''
    except KeyError:
        pass

    try:
        JENKINS_ARTIFACTS_PRESERVED_CHANGES_NOTIFICATION = os.environ['JENKINS_ARTIFACTS_PRESERVED_CHANGES_NOTIFICATION']
        if JENKINS_ARTIFACTS_PRESERVED_CHANGES_NOTIFICATION == 'false':
            JENKINS_ARTIFACTS_PRESERVED_CHANGES_NOTIFICATION=''
    except KeyError:
        pass

    try:
        BUILD_ORDER_CHANGES_NOTIFICATION = os.environ['BUILD_ORDER_CHANGES_NOTIFICATION']
        if BUILD_ORDER_CHANGES_NOTIFICATION == 'false':
            BUILD_ORDER_CHANGES_NOTIFICATION=''
    except KeyError:
        pass

    try:
        DEPENDANCY_REPORT_CHANGES_NOTIFICATION = os.environ['DEPENDANCY_REPORT_CHANGES_NOTIFICATION']
        if DEPENDANCY_REPORT_CHANGES_NOTIFICATION == 'false':
            DEPENDANCY_REPORT_CHANGES_NOTIFICATION=''
    except KeyError:
        pass

    try:
        BUILD_ORDER_DISCREPANCY_CHANGES_NOTIFICATION = os.environ['BUILD_ORDER_DISCREPANCY_CHANGES_NOTIFICATION']
        if BUILD_ORDER_DISCREPANCY_CHANGES_NOTIFICATION == 'false':
            BUILD_ORDER_DISCREPANCY_CHANGES_NOTIFICATION=''
    except KeyError:
        pass

    try:
        OUT_OF_BUILD_COPY_CHANGES_NOTIFICATION = os.environ['OUT_OF_BUILD_COPY_CHANGES_NOTIFICATION']
        if OUT_OF_BUILD_COPY_CHANGES_NOTIFICATION == 'false':
            OUT_OF_BUILD_COPY_CHANGES_NOTIFICATION=''
    except KeyError:
        pass

    try:
        OUT_OF_BUILD_VCE_DEPENDANCY_CHANGES_NOTIFICATION = os.environ['OUT_OF_BUILD_VCE_DEPENDANCY_CHANGES_NOTIFICATION']
        if OUT_OF_BUILD_VCE_DEPENDANCY_CHANGES_NOTIFICATION == 'false':
            OUT_OF_BUILD_VCE_DEPENDANCY_CHANGES_NOTIFICATION=''
    except KeyError:
        pass

    try:
        DUPLICATE_BUILD_JOBS_CHANGES_NOTIFICATION = os.environ['DUPLICATE_BUILD_JOBS_CHANGES_NOTIFICATION']
        if DUPLICATE_BUILD_JOBS_CHANGES_NOTIFICATION == 'false':
            DUPLICATE_BUILD_JOBS_CHANGES_NOTIFICATION=''
    except KeyError:
        pass

    try:
        OUT_OF_BUILD_MANUAL_DEPENDANCY_CHANGES_NOTIFICATION = os.environ['OUT_OF_BUILD_MANUAL_DEPENDANCY_CHANGES_NOTIFICATION']
        if OUT_OF_BUILD_MANUAL_DEPENDANCY_CHANGES_NOTIFICATION == 'false':
            OUT_OF_BUILD_MANUAL_DEPENDANCY_CHANGES_NOTIFICATION=''
    except KeyError:
        pass

    try:
        MAVEN_VERSION_SET_CHANGES_NOTIFICATION = os.environ['MAVEN_VERSION_SET_CHANGES_NOTIFICATION']
        if MAVEN_VERSION_SET_CHANGES_NOTIFICATION == 'false':
            MAVEN_VERSION_SET_CHANGES_NOTIFICATION=''
    except KeyError:
        pass
# 
# Create the authorization strings a single time for use in a couple of places
svn_auth_string = base64.encodestring('%s:%s' % (SVN_USERID, SVN_PASSWORD)).replace('\n', '')
jenkins_auth_string = base64.encodestring('%s:%s' % (JENKINS_USERID, JENKINS_PASSWORD)).replace('\n', '')

# For the dependencies that are too complicated to automate e.g. 
read_manual_dependencies_file()

print ''
print 'Start "' + GENISIS_BUILD_JOB + '" dependency analysis.'
print ''
print ''
parse_build_job(GENISIS_BUILD_JOB, indent_spaces)

print ''
print '"' + GENISIS_BUILD_JOB + '" dependency analysis complete'
print ''
print ''

# Create empty variables so that we can generate the reports and send email notifications in separate steps.
shell_jobs_file_differences = ''
all_maven_dependencies_file_differences = ''
maven_artifacts_generated_file_differences = ''
build_order_file_differences = ''
dependency_file_differences  = ''
build_discrepancies_file_differences = ''
out_of_build_copy_file_differences = ''
out_of_build_maven_vce_dependency_file_differences = ''
duplicate_build_jobs_file_differences = ''
out_of_build_manual_dependency_file_differences = ''
build_jobs_with_maven_version_change_dict_file_differences = ''

# Create the reports and if needed update the html file.
if shell_jobs:
    shell_jobs_file_differences = create_shell_jobs_report()
if maven_artifacts:
    all_maven_dependencies_file_differences    = create_all_maven_dependencies_report()
    maven_artifacts_generated_file_differences = create_maven_artifacts_generated_report()
if jenkins_artifacts:
    jenkins_artifacts_preserved_file_differences = create_jenkins_artifacts_preserved_report()
build_order_file_differences = create_build_order_report()
dependency_file_differences  = create_dependency_report()

# All reports below must be run after the create_dependency_report
if build_order_discrepancy:
    build_discrepancies_file_differences = create_build_discrepancies_report()
if out_of_build_copy_dict:
    out_of_build_copy_file_differences = create_out_of_build_copy_report()
if out_of_build_vce_dependency_dict:
    out_of_build_maven_vce_dependency_file_differences = create_out_of_build_maven_vce_dependency_report()
if duplicate_build_jobs:
    duplicate_build_jobs_file_differences = create_duplicate_build_jobs_report()
if out_of_build_manual_dependency_dict:
    out_of_build_manual_dependency_file_differences = create_out_of_build_manual_dependency_report()
if build_jobs_with_maven_version_change_dict:
    build_jobs_with_maven_version_change_dict_file_differences = create_build_jobs_with_maven_version_change_dict_report()

# Only run the email notifications if on the JENKINS_HOST and have a valid SMTP_SERVER and EMAIL_RECEIVER_LIST
if SMTP_SERVER and host == JENKINS_HOST and EMAIL_RECEIVER_LIST:
    # If enabled email the notification of the file changes
    if SHELL_JOBS_CHANGES_NOTIFICATION and shell_jobs_file_differences:
        email_file_differences(GENISIS_BUILD_JOB + ' shell jobs', shell_jobs_file_differences)

    if MAVEN_COMPLETE_DEPENDENCIES_CHANGES_NOTIFICATION and all_maven_dependencies_file_differences:
        email_file_differences(GENISIS_BUILD_JOB + ' all maven dependencies', all_maven_dependencies_file_differences)

    if MAVEN_ARTIFACTS_GENERATED_CHANGES_NOTIFICATION and maven_artifacts_generated_file_differences:
        email_file_differences(GENISIS_BUILD_JOB + ' maven VCE generated artifacts', maven_artifacts_generated_file_differences)

    if JENKINS_ARTIFACTS_PRESERVED_CHANGES_NOTIFICATION and jenkins_artifacts_preserved_file_differences:
        email_file_differences(GENISIS_BUILD_JOB + ' Jenkins preserved artifacts', jenkins_artifacts_preserved_file_differences)

    if BUILD_ORDER_CHANGES_NOTIFICATION and build_order_file_differences:
        email_file_differences(GENISIS_BUILD_JOB + ' build order', build_order_file_differences)

    if DEPENDANCY_REPORT_CHANGES_NOTIFICATION and dependency_file_differences:
        email_file_differences(GENISIS_BUILD_JOB + ' dependency report', dependency_file_differences)

    if BUILD_ORDER_DISCREPANCY_CHANGES_NOTIFICATION and build_discrepancies_file_differences:
        email_file_differences(GENISIS_BUILD_JOB + ' build order discrepancies', build_discrepancies_file_differences)

    if OUT_OF_BUILD_COPY_CHANGES_NOTIFICATION and out_of_build_copy_file_differences:
        email_file_differences(GENISIS_BUILD_JOB + ' out of build copy jobs', out_of_build_copy_file_differences)

    if OUT_OF_BUILD_VCE_DEPENDANCY_CHANGES_NOTIFICATION and out_of_build_maven_vce_dependency_file_differences:
        email_file_differences(GENISIS_BUILD_JOB + ' out of build VCE discrepancies', out_of_build_maven_vce_dependency_file_differences)

    if DUPLICATE_BUILD_JOBS_CHANGES_NOTIFICATION and duplicate_build_jobs_file_differences:
        email_file_differences(GENISIS_BUILD_JOB + ' duplicate build jobs', duplicate_build_jobs_file_differences)

    if OUT_OF_BUILD_MANUAL_DEPENDANCY_CHANGES_NOTIFICATION and out_of_build_manual_dependency_file_differences:
        email_file_differences(GENISIS_BUILD_JOB + ' out of build manual dependencies', out_of_build_manual_dependency_file_differences)

    if MAVEN_VERSION_SET_CHANGES_NOTIFICATION and build_jobs_with_maven_version_change_dict_file_differences:
       email_file_differences(GENISIS_BUILD_JOB + ' Maven jobs with version changes ', build_jobs_with_maven_version_change_dict_file_differences)