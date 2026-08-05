import assert from 'node:assert/strict';
import test from 'node:test';

import { parseBookmarksPage } from '../lib/parser.js';

function responseWithTweet(tweet) {
  return {
    data: {
      bookmark_timeline_v2: {
        timeline: {
          instructions: [{
            type: 'TimelineAddEntries',
            entries: [{
              entryId: `tweet-${tweet.rest_id}`,
              sortIndex: '1',
              content: { itemContent: { tweet_results: { result: tweet } } },
            }],
          }],
        },
      },
    },
  };
}

test('extracts author identity from the current user core and avatar shape', () => {
  const result = parseBookmarksPage(responseWithTweet({
    __typename: 'Tweet',
    rest_id: '100',
    legacy: { full_text: 'bookmark' },
    core: {
      user_results: {
        result: {
          rest_id: '200',
          core: { name: 'Display Name', screen_name: 'handle' },
          avatar: { image_url: 'https://example.test/avatar.jpg' },
          is_blue_verified: true,
          legacy: {
            description: 'Artist bio',
            location: 'Somewhere',
            entities: { url: { urls: [{ expanded_url: 'https://artist.example' }] } },
            profile_banner_url: 'https://example.test/banner.jpg',
            followers_count: 42,
            friends_count: 5,
          },
        },
      },
    },
  }));

  assert.deepEqual(result.tweets[0].author, {
    user_id: '200',
    screen_name: 'handle',
    name: 'Display Name',
    description: 'Artist bio',
    location: 'Somewhere',
    url: 'https://artist.example',
    profile_url: 'https://x.com/handle',
    profile_image_url: 'https://example.test/avatar.jpg',
    profile_banner_url: 'https://example.test/banner.jpg',
    verified: true,
    followers_count: 42,
    following_count: 5,
  });
});

test('keeps supporting the legacy user shape', () => {
  const result = parseBookmarksPage(responseWithTweet({
    __typename: 'Tweet',
    rest_id: '101',
    legacy: { full_text: 'bookmark' },
    core: {
      user_results: {
        result: {
          rest_id: '201',
          legacy: {
            screen_name: 'old_handle',
            name: 'Old Display Name',
            profile_image_url_https: 'https://example.test/old-avatar.jpg',
            verified: true,
            followers_count: 7,
          },
        },
      },
    },
  }));

  assert.deepEqual(result.tweets[0].author, {
    user_id: '201',
    screen_name: 'old_handle',
    name: 'Old Display Name',
    description: null,
    location: null,
    url: null,
    profile_url: 'https://x.com/old_handle',
    profile_image_url: 'https://example.test/old-avatar.jpg',
    profile_banner_url: null,
    verified: true,
    followers_count: 7,
    following_count: 0,
  });
});

test('extracts quoted author identity from the current user shape', () => {
  const result = parseBookmarksPage(responseWithTweet({
    __typename: 'Tweet',
    rest_id: '102',
    legacy: { full_text: 'bookmark' },
    quoted_status_result: {
      result: {
        __typename: 'Tweet',
        rest_id: '103',
        legacy: { full_text: 'quoted' },
        core: {
          user_results: {
            result: {
              rest_id: '203',
              core: { name: 'Quoted Name', screen_name: 'quoted_handle' },
            },
          },
        },
      },
    },
  }));

  assert.deepEqual(result.tweets[0].quoted_tweet.author, {
    user_id: '203',
    screen_name: 'quoted_handle',
    name: 'Quoted Name',
    description: null,
    location: null,
    url: null,
    profile_url: 'https://x.com/quoted_handle',
    profile_image_url: null,
    profile_banner_url: null,
    verified: false,
    followers_count: 0,
    following_count: 0,
  });
});
