export const CHANNELS_QUERY = /* GraphQL */ `
  query Channels {
    channels { id name }
  }
`;

export const CHANNEL_QUERY = /* GraphQL */ `
  query Channel($id: ID!) {
    channel(id: $id) { id name }
  }
`;

export const USER_QUERY = /* GraphQL */ `
  query User($id: ID!) {
    user(id: $id) { id displayName }
  }
`;

export const CREATE_USER_MUTATION = /* GraphQL */ `
  mutation CreateUser($displayName: String!) {
    createUser(displayName: $displayName) { id displayName }
  }
`;

export const CHANNEL_WORKSPACE_QUERY = /* GraphQL */ `
  query ChannelWorkspace($channelId: ID!) {
    messages(channelId: $channelId) {
      id channelId authorId content createdAt
      author { id displayName }
      reactions {
        messageId totalReactions
        summary { reactionType count }
        reactions { id messageId userId reactionType createdAt }
      }
    }
    polls(channelId: $channelId) {
      pollId channelId authorId question status durationMinutes
      closesAt createdAt closedAt totalVotes creationError
      options { optionId position text voteCount }
    }
  }
`;

export const CREATE_CHANNEL_MUTATION = /* GraphQL */ `
  mutation CreateChannel($name: String!) {
    createChannel(name: $name) { id name }
  }
`;

export const SEND_MESSAGE_MUTATION = /* GraphQL */ `
  mutation SendMessage($channelId: ID!, $authorId: ID!, $content: String!) {
    sendMessage(channelId: $channelId, authorId: $authorId, content: $content) {
      id channelId authorId content createdAt
    }
  }
`;

export const CREATE_POLL_MUTATION = /* GraphQL */ `
  mutation CreatePoll($input: CreatePollInput!, $idempotencyKey: String) {
    createPoll(input: $input, idempotencyKey: $idempotencyKey) {
      pollId channelId authorId question status durationMinutes
      closesAt createdAt closedAt totalVotes creationError
      options { optionId position text voteCount }
    }
  }
`;

export const POLL_QUERY = /* GraphQL */ `
  query Poll($id: ID!) {
    poll(id: $id) {
      pollId channelId authorId question status durationMinutes
      closesAt createdAt closedAt totalVotes creationError
      options { optionId position text voteCount }
    }
  }
`;

export const VOTE_MUTATION = /* GraphQL */ `
  mutation Vote($pollId: ID!, $voterId: ID!, $optionId: ID!) {
    vote(pollId: $pollId, voterId: $voterId, optionId: $optionId) {
      pollId voterId optionId castAt
    }
  }
`;

export const CLOSE_POLL_MUTATION = /* GraphQL */ `
  mutation ClosePoll($pollId: ID!, $authorId: ID!) {
    closePoll(pollId: $pollId, authorId: $authorId) {
      pollId channelId authorId question status durationMinutes
      closesAt createdAt closedAt totalVotes creationError
      options { optionId position text voteCount }
    }
  }
`;

export const ADD_REACTION_MUTATION = /* GraphQL */ `
  mutation AddReaction($messageId: ID!, $channelId: ID!, $userId: ID!, $reactionType: String!) {
    addReaction(
      messageId: $messageId
      channelId: $channelId
      userId: $userId
      reactionType: $reactionType
    ) { id messageId userId reactionType createdAt }
  }
`;

export const REMOVE_REACTION_MUTATION = /* GraphQL */ `
  mutation RemoveReaction($reactionId: ID!) {
    removeReaction(reactionId: $reactionId)
  }
`;

export const SEARCH_MESSAGES_QUERY = /* GraphQL */ `
  query SearchMessages($input: SearchMessagesInput!) {
    searchMessages(input: $input) {
      totalResults
      messages {
        id channelId authorId content createdAt editedAt
        has mentions links highlights
      }
    }
  }
`;

export const ALLOWED_GRAPHQL_DOCUMENTS = [
  CHANNELS_QUERY,
  CHANNEL_QUERY,
  USER_QUERY,
  CREATE_USER_MUTATION,
  CHANNEL_WORKSPACE_QUERY,
  CREATE_CHANNEL_MUTATION,
  SEND_MESSAGE_MUTATION,
  CREATE_POLL_MUTATION,
  POLL_QUERY,
  VOTE_MUTATION,
  CLOSE_POLL_MUTATION,
  ADD_REACTION_MUTATION,
  REMOVE_REACTION_MUTATION,
  SEARCH_MESSAGES_QUERY,
] as const;
