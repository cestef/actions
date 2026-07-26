#!/usr/bin/env bash
# Publish a staged directory onto an orphan branch of the repo itself.
#
# Shared by every action that writes a badge, so the token handling, the
# orphan-branch bootstrap and the contention retry are written once.
#
# Expects, in the environment:
#   PUBLISH_BRANCH   branch to write (created as an orphan if absent)
#   PUBLISH_TOKEN    token with contents:write
#   PUBLISH_REPO     owner/repo
#   PUBLISH_GIT_URL  git host, e.g. https://github.com
#   PUBLISH_STAGE    directory whose contents are copied over the branch
#   PUBLISH_MESSAGE  commit message
#   PUBLISH_USER     commit author name
#   PUBLISH_EMAIL    commit author email
set -euo pipefail

# The token goes in a header rather than the remote URL, so it cannot be echoed
# back by git's own error messages.
auth="AUTHORIZATION: Basic $(printf 'x-access-token:%s' "$PUBLISH_TOKEN" | base64 -w0)"
remote="${PUBLISH_GIT_URL%/}/$PUBLISH_REPO.git"

# Several badges can be published in the same run, so losing a push race is
# expected rather than exceptional: re-fetch and replay the staged files on top.
for attempt in 1 2 3 4 5; do
  work=$(mktemp -d)
  git init -q -b "$PUBLISH_BRANCH" "$work"
  git -C "$work" remote add origin "$remote"
  # An existing branch is extended; a missing one starts as a fresh orphan, so
  # the branch never carries the repository's own history.
  if git -C "$work" -c http.extraheader="$auth" fetch -q --depth 1 origin "$PUBLISH_BRANCH" 2>/dev/null; then
    git -C "$work" reset -q --hard FETCH_HEAD
  fi

  cp -R "$PUBLISH_STAGE"/. "$work"/
  git -C "$work" add -A
  if git -C "$work" diff --cached --quiet; then
    echo "publish: $PUBLISH_BRANCH already up to date"
    rm -rf "$work"
    exit 0
  fi
  git -C "$work" \
    -c user.name="$PUBLISH_USER" -c user.email="$PUBLISH_EMAIL" \
    commit -q -m "$PUBLISH_MESSAGE"

  if git -C "$work" -c http.extraheader="$auth" push -q origin "HEAD:$PUBLISH_BRANCH" 2>/dev/null; then
    echo "publish: wrote $PUBLISH_BRANCH"
    rm -rf "$work"
    exit 0
  fi
  echo "publish: $PUBLISH_BRANCH moved under us, retrying ($attempt/5)"
  rm -rf "$work"
  sleep $((attempt * 2))
done

echo "::error::publish: could not update $PUBLISH_BRANCH after 5 attempts"
exit 1
