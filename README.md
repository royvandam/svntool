# SVNTool

## Features

This tool originated at project where a single root SVN repository contained multiple sub SVN repositories which are managed manualy and individualy during development. Obviously this is slow, annoying and error prone. Svntool allows you to define one or more project manifests in the root SVN repository containing the paths to the sub reposities you want to manage. And interact with said manifest in a more or less git like manner.

The following features have been implemented:

- branch
  - checkout
  - create
  - delete
  - diff       Compare entire remote branches
  - list
  - merge      Trunk or branch to local checkout
  - origin     Finds the origin revision of a branch
- commit
- diff
- revert
- log
  - Search for commits containing specific words
  - Generating revision sets
- status (with colors :))
- update
  - HEAD
  - Loading revision sets

Features to be implemented:

 - stash
   - push     Create a patch file on a stack and revert changes
   - pop      Remove a patch file from stack and apply

## Dependencies

 - termcolor
 - svn
