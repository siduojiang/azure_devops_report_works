#!/usr/bin/python

import argparse
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
from azure.devops.v6_0.work_item_tracking.models import Wiql

def parse_args():
    '''Defines cmdline arguments'''
    parser = argparse.ArgumentParser()
    parser.add_argument('--access-token', help='Azure Dev Ops access token')
    parser.add_argument('--org-name', help='Azure Dev Ops organization')
    parser.add_argument('--tag', default = None, help='Tag by which to filter ')
    parser.add_argument('--project-name', help='Project Name for which to report works')
    return parser.parse_args()

class ReportProjectWorks(object):
    """Generates report for Azure Devops Backlogs"""
    def __init__(self,
                 access_token,
                 organization,
                 tag = None,
                 project_name = 'KM Interview'):

        self.project_name = project_name
        self.personal_access_token = access_token
        self.organization_url = organization
        self.tag = tag

        #Create a connection to the org
        self.credentials = BasicAuthentication('', self.personal_access_token)
        self.connection = Connection(base_url=self.organization_url, creds=self.credentials)

    def wiql_query(self):
        """Executes WIQL query against devops project"""
        wit_client = self.connection.clients.get_work_item_tracking_client()

        #First query generates the WorkItems
        work_items_query="""
                         SELECT [System.Title]
                         FROM WorkItems
                         WHERE [System.TeamProject] = '%s'
                         """ %str(self.project_name)
        #Second query generates the links between work items in order to get the proper hierarchy
        work_items_link_query="""
                              SELECT [System.Id], [System.WorkItemType]
                              FROM WorkItemLinks
                              WHERE ([System.Links.LinkType] = 'System.LinkTypes.Hierarchy-Forward')
                              AND Target.[System.TeamProject] = '%s'
                              """ %str(self.project_name)

        #If tag is supplied, filter based on the presence of the tag
        if self.tag is not None:
            work_items_query += "AND [System.Tags] CONTAINS '%s'" %str(self.tag)
            work_items_link_query += """
                                     AND Target.[System.Tags] CONTAINS '%s'
                                     ORDER BY [System.Id]
                                     MODE (Recursive, ReturnMatchingChildren)
                                     """ %str(self.tag)

        #Otherwise, generate an ordering based on System.Id
        else:
            work_items_link_query += """
                                     ORDER BY [System.Id]
                                     MODE (Recursive, ReturnMatchingChildren)
                                     """

        #submit the queries, and extract the work_items and their relations
        wiql_works = wit_client.query_by_wiql(Wiql(query=work_items_query)).work_items
        wiql_links = wit_client.query_by_wiql(Wiql(query=work_items_link_query)).work_item_relations

        if wiql_works:
            # WIQL query gives a WorkItemReference with ID only
            # Get the corresponding WorkItem from id
            work_items = [wit_client.get_work_item(int(res.id)) for res in wiql_works]

            #Generate a mapping between work id and the output string to be printed
            #This generates the lookup table when printing the messages
            works = {}
            for work_item in work_items:
                work_item = work_item.as_dict()
                item_id = work_item['id']
                works[item_id] = self.get_fields_output(work_item)

            #return the lookup table of strings, and the raw links table
            return works, wiql_links
        else:
            return [], []

    @staticmethod
    def get_hierarchy(wiql_links):
        """Parses the returned hierarchy and hash target ids to source pairs"""
        #Gather the hierarchy link structure
        #Key is the target id (parents), value is the source id (children of parent)
        hierarchy = {}

        #maintain a list of head_nodes
        #These are the top most levels, and we will need to iterate through each
        #in order to generate the full report
        head_nodes = []

        for result in wiql_links:
            result = result.as_dict()

            target_id = result['target']['id']

            #Head node -- when 'source' is not present, it is a head node
            if 'source' not in result.keys():
                hierarchy[target_id] = []
                head_nodes.append(target_id)

            #append this target to the source
            else:
                source_id = result['source']['id']
                hierarchy[source_id].append(target_id)
                if target_id not in hierarchy:
                    hierarchy[target_id] = []
        return head_nodes, hierarchy

    @staticmethod
    def get_fields_output(work_item):
        """Generates desired output for work_item"""
        item_id = work_item['id']
        item_type = work_item['fields']['System.WorkItemType']
        item_name = work_item['fields']['System.Title']
        return r" (%d)[%s] %s" %(item_id, item_type, item_name)

    def generate_report(self):
        """Main function"""
        #Query desired project
        works, wiql_links = self.wiql_query()
        head_nodes, links = self.get_hierarchy(wiql_links)

        #recursively print the results
        def recursive_search(node, indents = 0):
            """Recursively prints all children of report"""
            #print node first before recursive call
            print('|' + indents * '--' + works[node])

            #base case
            if not links[node]:
                return

            #recursively call all source nodes that follow target
            for tail_node in links[node]:
                recursive_search(tail_node, indents + 1)

        #Print from every head node
        for node in head_nodes:
            recursive_search(node)

if __name__ == '__main__':
    args = parse_args()
    ReportProjectWorks(args.access_token.strip(),
                       'https://dev.azure.com/' + args.org_name,
                       args.tag,
                       args.project_name).generate_report()
