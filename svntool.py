#!/bin/env python3

import os, sys, subprocess, re
import argparse
import svn.local as svn
import svn.constants as svnc
import xml.etree.ElementTree as xml

if sys.stdout.isatty():
    from termcolor import colored
else:
    def colored(text, color):
        return text

SVN_STATUS_MASK = (
    svnc.ST_ADDED,
    svnc.ST_CONFLICTED,
    svnc.ST_DELETED,
    #svnc.ST_EXTERNAL,
    #svnc.ST_IGNORED,
    svnc.ST_INCOMPLETE,
    svnc.ST_MERGED,
    svnc.ST_MISSING,
    svnc.ST_MODIFIED,
    #svnc.ST_NONE,
    #svnc.ST_NORMAL,
    svnc.ST_OBSTRUCTED,
    svnc.ST_REPLACED,
    #svnc.ST_UNVERSIONED,
)

SVN_COMMIT_MASK = (
    svnc.ST_ADDED,
    svnc.ST_DELETED,
    svnc.ST_MERGED,
    svnc.ST_MODIFIED,
    svnc.ST_REPLACED,
) 

SVN_ST_COLOR_MAP = {
    svnc.ST_ADDED:      'green',
    svnc.ST_DELETED:    'red',
    svnc.ST_MODIFIED:   'yellow',
    svnc.ST_REPLACED:   'blue',
    svnc.ST_MERGED:     'cyan',
    svnc.ST_CONFLICTED: 'magenta'
}

def readConfig(path):
    with open(path, 'r') as fd:
        for entry in fd.readlines():
            entry = entry.strip()
            if entry.startswith('#') or not len(entry):
                continue
            yield entry

class Repo:
    def __init__(self, path):
        self.local_path = path
        self.client = svn.LocalClient(path)
        self._updateInfo()

        if not os.path.exists(self.local_path):
            raise RuntimeError("'%s' does not exist on disk" % self)

    def __str__(self):
        return colored(self.local_path, 'blue')

    @property
    def revision(self):
        return self.info['commit#revision']

    @property
    def baseurl(self):
        return self.info['repository_root'] + '/' + self.local_path

    @property
    def currentPath(self):
        return re.search(r'(tags|branches)/[^/]+|trunk', self.info['url'])[0]

    @property
    def currentBranch(self):
        return os.path.basename(self.currentPath)

    def _updateInfo(self):
        self.info = self.client.info()

    def _exec(self, *args):
        return subprocess.check_output(args, stderr=subprocess.PIPE, universal_newlines=True).splitlines()
    
    def _printError(self, e):
        sys.stderr.write("Failed (%d):\n" % e.returncode)
        for line in e.stderr.splitlines():
            sys.stderr.write("  %s\n" % line)

    def makeUrl(self, parts):
        path = [self.baseurl]
        path.extend(parts)
        return '/'.join(path)

    def pendingChanges(self, mask=SVN_STATUS_MASK):
        changes = []
        for change in self.client.status():
            if change.type not in mask:
                continue
            changes.append(change)
        return changes

    def findBranchOrigin(self, branch):
        if branch == None:
            branch = self.currentBranch
        
        if branch != 'trunk':
            if not self.branchExists(branch):
                sys.stderr.write("'%s' branch '%s' does not exist, skipping\n" % (self, branch))
                return -1
            branch_url = self.makeUrl(['branches', branch])
        else:
            branch_url = self.makeUrl([branch])
        
        result = self._exec('svn', 'log', '--stop-on-copy', '--limit', '1', '-r', '0:HEAD', branch_url)
        origin = int(re.match(r'r([0-9]+)', result[1]).group(1))
        sys.stdout.write("%-35s '%s' origin rev #%d\n" % (self, branch, origin))

    def getBranches(self):
        branch_url = self.makeUrl(['branches'])
        return list(map(lambda e: e.rstrip('/'), self._exec('svn', 'ls', branch_url)))

    def branchExists(self, name):
        try:
            branch_url = self.makeUrl(['branches', name])
            self._exec('svn', 'list', branch_url)
            return True
        except subprocess.CalledProcessError:
            return False

    def createBranchFromTrunk(self, name):
        if self.branchExists(name):
            print("'%s' branch '%s' exists" % (self, name))
            return

        print("'%s' creating branch '%s' from trunk" % (self, name))
        trunk_url = self.makeUrl(['trunk'])
        branch_url = self.makeUrl(['branches', name])
        commitmsg = '-m"Creating branch \'%s\' from trunk."' % name
        try:
            self._exec('svn', 'copy', trunk_url, branch_url, commitmsg)
        except subprocess.CalledProcessError as e:
            self._printError(e)

    def createBranchFromBranch(self, source, target):
        if not self.branchExists(source):
            print("'%s' source branch '%s' does not exist" % (self, source))
            return

        if self.branchExists(target):
            print("'%s' branch '%s' exists" % (self, target))
            return

        print("'%s' creating branch '%s' from branch '%s'" % (self, target, source))
        source_url = self.makeUrl(['branches', source])
        target_url = self.makeUrl(['branches', target])
        commitmsg = '-m"Creating branch \'%s\' from branch \'%s\'."' % (target, source)
        try:
            self._exec('svn', 'copy', source_url, target_url, commitmsg)
        except subprocess.CalledProcessError as e:
            self._printError(e)

    def checkoutBranch(self, name):
        if self.currentBranch == name:
            sys.stderr.write("'%s' already on branch '%s'\n" % (self, name))
            return

        if name != 'trunk':
            if not self.branchExists(name):
                sys.stderr.write("'%s' branch '%s' does not exist, skipping\n" % (self, name))
                return 
            branch_url = self.makeUrl(['branches', name])
        else:
            branch_url = self.makeUrl([name])

        print("'%s' checking out branch '%s'" % (self, name))
        try:
            self._exec('svn', 'switch', branch_url, self.local_path)
        except subprocess.CalledProcessError as e:
            self._printError(e)

    def deleteBranch(self, name, archive=False):
        if not self.branchExists(name):
            sys.stderr.write("'%s' branch '%s' does not exist\n" % (self, name))
            return
        
        if self.currentPath.endswith(name):
            sys.stderr.write("'%s' is currently on branch '%s', cannot delete\n" % (self, name))
            return

        branch_url = self.makeUrl(['branches', name])
        
        try:
            if not archive:
                print("'%s' deleting branch '%s'" % (self, name))
                commitmsg = '-m"Deleting branch \'%s\'"' % name
                self._exec('svn', 'rm', branch_url, commitmsg)
            else:
                print("'%s' archiving branch '%s'" % (self, name))
                commitmsg = '-m"Archiving branch \'%s\'"' % name
                archive_url = self.makeUrl(['branches', name + '.closed'])
                self._exec('svn', 'rename', branch_url, archive_url, commitmsg)
        except subprocess.CalledProcessError as e:
            self._printError(e)

    def diffBranch(self, old, new=None, fd=sys.stdout):
        if old != 'trunk':
            if not self.branchExists(old):
                sys.stderr.write("'%s' branch '%s' does not exist, skipping\n" % (self, old))
                return
            old_url = self.makeUrl(['branches', old])
        else:
            old_url = self.makeUrl(['trunk'])

        if new == None:
            new = self.currentPath.replace("branches/", "")

        if new != 'trunk':
            if not self.branchExists(new):
                sys.stderr.write("'%s' branch '%s' does not exist, skipping\n" % (self, new))
                return
            new_url = self.makeUrl(['branches', new])
        else:
            new_url = self.makeUrl(['trunk'])

        if old == new:
            sys.stderr.write("'%s' can not diff '%s' against '%s'\n" % (self, new, old))
            return

        try:
            for line in self._exec('svn', 'diff', '--old', old_url, '--new', new_url):
                fd.write(line + '\n')
        except subprocess.CalledProcessError as e:
            self._printError(e)


    def update(self, revision=None):
        cmd = ['svn', 'up']
        if revision != None:
            cmd.extend(['-r', revision])
        cmd.append(self.local_path)

        try:
            sys.stdout.write("'%s' updating... " % self)
            sys.stdout.flush()
            self._exec(*cmd)
            self._updateInfo()
            sys.stdout.write("at revision #%d\n" % self.revision)
        except subprocess.CalledProcessError as e:
            self._printError(e)

    def commit(self, message):
        changes = self.pendingChanges(mask=SVN_COMMIT_MASK)
        if len(changes) == 0:
            print("'%s' no pending changes, skipping." % self)
            return
        paths = [ c.name for c in changes ]

        sys.stdout.write("'%s' committing %d changes... " % (self, len(changes)))
        sys.stdout.flush()
        try:
            self._exec('svn', 'commit', *paths, '-m', '"%s"' % message)
            self.client.update()
            self._updateInfo()
            sys.stdout.write("at revision #%s\n" % self.revision)
        except subprocess.CalledProcessError as e:
            self._printError(e)

    def merge(self, branch, dryrun=False, revision=None):
        if branch == self.currentBranch:
            sys.stderr.write("'%s' can not merge branch '%s' with itself\n" % (self, branch))
            return
        elif branch != 'trunk':
            if not self.branchExists(branch):
                sys.stderr.write("'%s' branch '%s' does not exist, skipping\n" % (self, branch))
                return
            branch_url = self.makeUrl(['branches', branch])
        else:
            branch_url = self.makeUrl(['trunk'])

        cmd = ['svn', 'merge', '--non-interactive']
        if dryrun:
            cmd.append('--dry-run')
        if revision:
            cmd.extend(['-r', revision])
        cmd.extend([branch_url, self.local_path])

        try:
            print("'%s' merging changes from from '%s' into '%s'" % (self, branch, self.currentBranch))
            for line in self._exec(*cmd):
                print("  ", line)
        except subprocess.CalledProcessError as e:
            self._printError(e)

    def log(self, limit=10, search=None, rev_set=False, offset=0):
        cmd = ['svn', 'log', self.baseurl, '--xml', '-l', limit]
        if search != None:
            cmd.extend(['--search', search])
        result = self._exec(*cmd)
        tree = xml.ElementTree(xml.fromstring("\n".join(result)))

        if (search != None or rev_set) and len(tree.getroot()) == 0:
            return

        if rev_set:
            revision = int(tree.getroot()[0].get('revision')) + offset
            sys.stdout.write("%s @ %s\n" % (self, revision))
            return

        sys.stdout.write(str(self))

        branch = self.currentPath
        if branch != "trunk":
            sys.stdout.write(colored(" @ " + branch, 'green'))
        if search != None:
            sys.stdout.write(" filtered by '%s'" % colored(search, 'green'))
        sys.stdout.write('\n')

        for logentry in tree.getroot():
            header = "%s %s %-20s" % (
                colored("#%6s" % logentry.get('revision'), 'yellow'),
                colored(logentry.find('date').text, 'magenta'),
                colored(logentry.find('author').text, 'red'),
            )
            message = logentry.find('msg').text
            if message != None:
                message = message.splitlines()[0]
            sys.stdout.write('  %-60s  %s\n' % (header, message))
    
    def diff(self, fd=sys.stdout):
        for line in self._exec('svn', 'diff', self.local_path):
            fd.write(line + '\n')

    def revert(self):
        sys.stdout.write("'%s' reverting changes... " % self)
        sys.stdout.flush()
        try:
            self._exec('svn', 'revert', '--recursive', self.local_path)
            sys.stdout.write('done\n')
        except subprocess.CalledProcessError as e:
            self._printError(e)

    def status(self):
        sys.stdout.write("%-50s %s" % (self,
            colored("#%6s" % self.revision, 'yellow')))
        branch = self.currentPath 
        if branch != "trunk":
            sys.stdout.write(colored(" @ " + branch, 'green'))
        sys.stdout.write("\n")
        for change in self.pendingChanges():
            sys.stdout.write(" - %s %s\n" % (
                colored("%-15s" % change.type_raw_name, SVN_ST_COLOR_MAP.get(change.type, 'white')),
                change.name
            ))

class Branch:
    def run(self, repos, args):
        actions = [
            'checkout',
            'create',
            'delete',
            'diff',
            'list',
            'merge',
            'origin',
        ]

        parser = argparse.ArgumentParser('svntool branch')
        parser.add_argument('action', metavar='action', choices=actions,
            help="Action to perform: " + ", ".join(actions))
        parser.add_argument('args', nargs=argparse.REMAINDER,
            help="Arguments for action")
        subargs = parser.parse_args(args)

        self.__getattribute__('_' + subargs.action)(repos, subargs.args)

    def _list(self, repos, args):
        for repo in repos:
            print("%s:" % repo)
            for branch in repo.getBranches():
                print("  " + branch)

    def _origin(self, repos, args):
        parser = argparse.ArgumentParser('svntool branch origin', description='Locate the branch point of a branch.')
        parser.add_argument('name', default=None, nargs='?',
            help="Name of the branch to find the origin for. (default: Current working branch)")
        args = parser.parse_args(args)

        for repo in repos:
            repo.findBranchOrigin(args.name)

    def _create(self, repos, args):
        parser = argparse.ArgumentParser('svntool branch create')
        parser.add_argument('name', help="Name of the branch to create")
        parser.add_argument('--branch', '-b', required=False,
            help="Create the new branch from this branch")
        args = parser.parse_args(args)

        if args.branch:
            for repo in repos:
                repo.createBranchFromBranch(args.branch, args.name)
        else:
            for repo in repos:
                repo.createBranchFromTrunk(args.name)

    def _diff(self, repos, args):
        parser = argparse.ArgumentParser('svntool branch diff')
        parser.add_argument('--old', '-o', default='trunk',
            help="Name of the branch to compare the new branch against. (default: trunk)")
        parser.add_argument('--new', '-n', required=False, default=None,
            help="Name of the branch to compare against the old branch. (default: current working branch)")
        parser.add_argument('--filename', '-f', required=False,
            help="path to write the diff output to (default: stdout)")
        args = parser.parse_args(args)

        if args.filename:
            with open(args.filename, 'w') as fd:
                for repo in repos:
                    repo.diff(args.old, args.new, fd)
                fd.flush()
        else:
            for repo in repos:
                repo.diffBranch(args.old, args.new, sys.stdout)

    def _delete(self, repos, args):
        parser = argparse.ArgumentParser('svntool branch delete')
        parser.add_argument('name',
            help="Name of the branch to delete")
        parser.add_argument('--archive', '-a', action='store_true', default=False,
            help="Archive the branch to .closed instead of deleting it.")
        args = parser.parse_args(args)

        for repo in repos:
            repo.deleteBranch(args.name, args.archive)

    def _checkout(self, repos, args):
        parser = argparse.ArgumentParser('svntool branch checkout')
        parser.add_argument('name', help="Name of the branch to checkout")
        args = parser.parse_args(args)

        for repo in repos:
            repo.checkoutBranch(args.name)

    def _merge(self, repos, args):
        parser = argparse.ArgumentParser('svntool branch merge')
        parser.add_argument('name',
            help="Name of the branch to merge into the currently checkout out branch")
        parser.add_argument('--dry-run', '-d', action='store_true',
            help="Try operation but make no changes")
        parser.add_argument('--revision', '-r', required=False, default=None,
            help="Perform merge over explict revision range")
        args = parser.parse_args(args)

        for repo in repos:
            repo.merge(args.name, args.dry_run, args.revision)

class Commit:
    def run(self, repos, args):
        parser = argparse.ArgumentParser('svntool commit')
        parser.add_argument('--message', '-m', required=True, help="Commit message")
        subargs = parser.parse_args(args)

        for repo in repos:
            repo.commit(subargs.message)

class Status:
    def run(self, repos, args):
        for repo in repos:
            repo.status()

class Update:
    def loadRevSet(self, path):
        def _err(line, msg):
            sys.stderr.write("Invalid rev set entry on line #%d, %s\n" % (line, msg))

        revset = {}
        for index, entry in enumerate(readConfig(path)):
            entry = entry.split("@")
            if len(entry) != 2:
                _err(index+1, "Definition must contain '@' between repository and revision.")
                continue
            revision = entry[1].strip()
            if not revision.isdigit():
                _err(index+1, "Revision must be a number")
                continue
            repository = entry[0].strip()
            revset[repository] = revision

        return revset

    def run(self, repos, args):
        parser = argparse.ArgumentParser('svntool update')
        parser.add_argument('--rev-set', required=False, default=None,
            help="Use revision set file containting for each repository the explicit revision to checkout. " +
                 "(eg: 'Libraries/MyRepo @ 133742', hint: use 'log --rev-set')")
        subargs = parser.parse_args(args)

        revset = {}
        if subargs.rev_set != None:
            revset = self.loadRevSet(subargs.rev_set)

        for repo in repos:
            repo.update(revision=revset.get(repo.local_path, None))

class Log:
    def run(self, repos, args):
        parser = argparse.ArgumentParser('svntool log')
        parser.add_argument('--search', '-s', default=None,
            help="Filter commits by query e.g. author or words in commit message")
        parser.add_argument('--limit', '-l', default="10",
            help="Limit number of commits (default=10)")
        parser.add_argument('--rev-set', action="store_true",
            help="Generate repository revision set based on the first commit found.")
        parser.add_argument('--offset', '-o', required=False, default="0",
            help="Offset to apply to the revision number when generating a revision set.")
        subargs = parser.parse_args(args)

        if not subargs.offset.lstrip('-+').isdigit():
            sys.stderr.write("Error: offset must be an integral number\n")
            sys.exit(1)

        for repo in repos:
            repo.log(subargs.limit, subargs.search,
                     subargs.rev_set, int(subargs.offset))

class Diff:
    def run(self, repos, args):
        for repo in repos:
            repo.diff()

class Revert:
    def run(self, repos, args):
        for repo in repos:
            repo.revert()

class Svntool:
    def __init__(self):
        self.commands = {
            'branch': Branch,
            'commit': Commit,
            'diff': Diff,
            'log': Log,
            'status': Status,
            'revert': Revert,
            'up': Update,
            'update': Update,
        }

    def loadConfig(self, path, check=False):
        repos = list()
        for entry in readConfig(path):
            repos.append(Repo(entry))
        return repos

    def run(self):
        parser = argparse.ArgumentParser('svntool')
        parser.add_argument('config', 
            help="Path to configuration file which contains line by line the repositories to act on.")
        parser.add_argument('--repo', '-r', required=False, default=None,
            help="Explicit single repository to act up on instead of all the entries in the configuration file.")
        parser.add_argument('command', metavar="command", choices=self.commands.keys(),
            help="Command to execute: " + ", ".join(self.commands.keys()))
        parser.add_argument('args', nargs=argparse.REMAINDER,
            help="Arguments for command (hint: use 'svntool [command] -h' to list available suboptions)")
        args = parser.parse_args()

        try:
            repos = self.loadConfig(args.config)
        except Exception as e:
            sys.stderr.write("Error - " +  str(e))
            sys.exit(1)

        if args.repo:
            repos = [ r for r in repos if str(r).endswith(args.repo) ]
            if not len(repos):
                sys.stderr.write("Unknown repository: " + args.repo + "\n")
                sys.exit(1)

        try:
            self.commands[args.command]().run(repos, args.args)
        except FileNotFoundError as e:
            sys.stderr.write("%s\n" % e)
            sys.exit(1)

if __name__ == "__main__":
    svntool = Svntool()
    svntool.run()