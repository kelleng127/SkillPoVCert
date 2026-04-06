/* eslint-disable  func-names */
/* eslint-disable  no-console */

const Alexa = require('ask-sdk-core');
const APP_NAME = "Template Seven";
const messages = {
  NOTIFY_MISSING_PERMISSIONS: 'Please enable profile permissions in the Amazon Alexa app.',
  ERROR: 'Uh Oh. Looks like something went wrong.'
};

const FULL_NAME_PERMISSION = "alexa::profile:name:read";
const EMAIL_PERMISSION = "alexa::profile:email:read";
const MOBILE_PERMISSION = "alexa::profile:mobile_number:read";


const LaunchRequestHandler = {
    canHandle(handlerInput) {
        return Alexa.getRequestType(handlerInput.requestEnvelope) === 'LaunchRequest';
    },
    async handle(handlerInput) {
        const attributesManager = handlerInput.attributesManager;
        const sessionAttributes = attributesManager.getSessionAttributes() || {};
        
        let userFirstTime = sessionAttributes['userFirstTime'];

        if (userFirstTime) {
            const speakOutput = "Welcome! This skill will collect your personal information. If you're curious about what kind of data might be collected, please say I want to know. Or, if you prefer to skip this for now, you can simply say I don't want to know. Remember, feel free to ask me anytime by saying tell me what data is collected.";
            return handlerInput.responseBuilder
                .speak(speakOutput)
                .getResponse();
        } else {
            attributesManager.setPersistentAttributes({ userFirstTime: true });
            await attributesManager.savePersistentAttributes();

            const speakOutput = 'Welcome Back! Remember, feel free to ask me anytime by saying tell me what data is collected. You can say yes to enter the skill.';
            return handlerInput.responseBuilder
                .speak(speakOutput)
                .getResponse();
        }
    }
};

const WantKnowIntentHandler = {
    canHandle(handlerInput) {
        return handlerInput.requestEnvelope.request.type === 'IntentRequest'
            && handlerInput.requestEnvelope.request.intent.name === 'WantKnowIntent';
    },
    handle(handlerInput) {
    const speakOutput = 'This skill will seek your number, name, and email permissions. Please say yes to continue or no to exit.';
    return handlerInput.responseBuilder
      .speak(speakOutput)
      .reprompt(speakOutput)
      .getResponse();
    }
}

const DataCollectionIntentHandler = {
    canHandle(handlerInput) {
        return handlerInput.requestEnvelope.request.type === 'IntentRequest'
            && handlerInput.requestEnvelope.request.intent.name === 'DataCollectionIntent';
    },
    handle(handlerInput) {
    const speakOutput = 'This skill will seek your number, name, and email permissions. Please respond to any pending questions to continue, or say no if you wish to end the session.';
    return handlerInput.responseBuilder
      .speak(speakOutput)
      .reprompt(speakOutput)
      .getResponse();
    }
}


const NoExitIntentHandler = {
    canHandle(handlerInput) {
        return handlerInput.requestEnvelope.request.type === 'IntentRequest'
            && handlerInput.requestEnvelope.request.intent.name === 'NoExitIntent';
    },
    handle(handlerInput) {
    const speakOutput = 'Thank you! Goodbye.';
    return handlerInput.responseBuilder
      .speak(speakOutput)
      .getResponse();
    }
}

const EnterSkillIntentHandler = {
  canHandle(handlerInput) {
    return handlerInput.requestEnvelope.request.type === 'IntentRequest' && handlerInput.requestEnvelope.request.intent.name === 'EnterSkillIntent';
  },
  handle(handlerInput) {
    const speechText = `Hello. You can say: what's my name, what's my email, or, what's my phone number.`;
    const reprompt = `say: what's my name, what's my email, or, what's my phone number.`;

    return handlerInput.responseBuilder
      .speak(speechText)
      .reprompt(reprompt)
      .withSimpleCard(APP_NAME, speechText)
      .getResponse();
  },
};

const GreetMeIntentHandler = {
  canHandle(handlerInput) {
    return handlerInput.requestEnvelope.request.type === 'IntentRequest'
      && handlerInput.requestEnvelope.request.intent.name === 'GreetMeIntent';
  },
  async handle(handlerInput) {
    const { serviceClientFactory, responseBuilder } = handlerInput;
    try {
      const upsServiceClient = serviceClientFactory.getUpsServiceClient();
      const profileName = await upsServiceClient.getProfileName();
      const speechResponse = `Your name is, ${profileName}`;
      return responseBuilder
                      .speak(speechResponse)
                      .withSimpleCard(APP_NAME, speechResponse)
                      .getResponse();
    } catch (error) {
      console.log(JSON.stringify(error));
      if (error.statusCode == 403) {
        return responseBuilder
        .speak(messages.NOTIFY_MISSING_PERMISSIONS)
        .withAskForPermissionsConsentCard([FULL_NAME_PERMISSION])
        .getResponse();
      }
      console.log(JSON.stringify(error));
      const response = responseBuilder.speak(messages.ERROR).getResponse();
      return response;
    }
  },
}

const EmailIntentHandler = {
  canHandle(handlerInput) {
    return handlerInput.requestEnvelope.request.type === 'IntentRequest'
      && handlerInput.requestEnvelope.request.intent.name === 'EmailIntent';
  },
  async handle(handlerInput) {
    const { serviceClientFactory, responseBuilder } = handlerInput;
    try {
      const upsServiceClient = serviceClientFactory.getUpsServiceClient();
      const profileEmail = await upsServiceClient.getProfileEmail();
      if (!profileEmail) {
        const noEmailResponse = `It looks like you don\'t have an email set. You can set your email from the companion app.`
        return responseBuilder
                      .speak(noEmailResponse)
                      .withSimpleCard(APP_NAME, noEmailResponse)
                      .getResponse();
      }
      const speechResponse = `Your email is, ${profileEmail}`;
      return responseBuilder
                      .speak(speechResponse)
                      .withSimpleCard(APP_NAME, speechResponse)
                      .getResponse();
    } catch (error) {
      console.log(JSON.stringify(error));
      if (error.statusCode == 403) {
        return responseBuilder
        .speak(messages.NOTIFY_MISSING_PERMISSIONS)
        .withAskForPermissionsConsentCard([EMAIL_PERMISSION])
        .getResponse();
      }
      console.log(JSON.stringify(error));
      const response = responseBuilder.speak(messages.ERROR).getResponse();
      return response;
    }
  },
}

const MobileIntentHandler = {
  canHandle(handlerInput) {
    return handlerInput.requestEnvelope.request.type === 'IntentRequest'
      && handlerInput.requestEnvelope.request.intent.name === 'MobileIntent';
  },
  async handle(handlerInput) {
    const { serviceClientFactory, responseBuilder } = handlerInput;
    try {
      const upsServiceClient = serviceClientFactory.getUpsServiceClient();
      const profileMobileObject = await upsServiceClient.getProfileMobileNumber();
      if (!profileMobileObject) {
        const errorResponse = `It looks like you don\'t have a mobile number set. You can set your mobile number from the companion app.`
        return responseBuilder
                      .speak(errorResponse)
                      .withSimpleCard(APP_NAME, errorResponse)
                      .getResponse();
      }
      const profileMobile = profileMobileObject.phoneNumber;
      const speechResponse = `Your mobile number is, <say-as interpret-as="telephone">${profileMobile}</say-as>`;
      const cardResponse = `Your mobile number is, ${profileMobile}`
      return responseBuilder
                      .speak(speechResponse)
                      .withSimpleCard(APP_NAME, cardResponse)
                      .getResponse();
    } catch (error) {
      console.log(JSON.stringify(error));
      if (error.statusCode == 403) {
        return responseBuilder
        .speak(messages.NOTIFY_MISSING_PERMISSIONS)
        .withAskForPermissionsConsentCard([MOBILE_PERMISSION])
        .getResponse();
      }
      console.log(JSON.stringify(error));
      const response = responseBuilder.speak(messages.ERROR).getResponse();
      return response;
    }
  },
}

const HelpIntentHandler = {
  canHandle(handlerInput) {
    return handlerInput.requestEnvelope.request.type === 'IntentRequest'
      && handlerInput.requestEnvelope.request.intent.name === 'AMAZON.HelpIntent';
  },
  handle(handlerInput) {
    const speechText = 'You can say hello to me!';

    return handlerInput.responseBuilder
      .speak(speechText)
      .reprompt(speechText)
      .withSimpleCard('Hello World', speechText)
      .getResponse();
  },
};

const CancelAndStopIntentHandler = {
  canHandle(handlerInput) {
    return handlerInput.requestEnvelope.request.type === 'IntentRequest'
      && (handlerInput.requestEnvelope.request.intent.name === 'AMAZON.CancelIntent'
        || handlerInput.requestEnvelope.request.intent.name === 'AMAZON.StopIntent');
  },
  handle(handlerInput) {
    const speechText = 'Goodbye!';

    return handlerInput.responseBuilder
      .speak(speechText)
      .getResponse();
  },
};

const SessionEndedRequestHandler = {
  canHandle(handlerInput) {
    return handlerInput.requestEnvelope.request.type === 'SessionEndedRequest';
  },
  handle(handlerInput) {
    console.log(`Session ended with reason: ${handlerInput.requestEnvelope.request.reason}`);

    return handlerInput.responseBuilder.getResponse();
  },
};

const ErrorHandler = {
  canHandle() {
    return true;
  },
  handle(handlerInput, error) {
    console.log(`Error handled: ${error.message}`);

    return handlerInput.responseBuilder
      .speak('Sorry, I can\'t understand the command. Please say again.')
      .reprompt('Sorry, I can\'t understand the command. Please say again.')
      .getResponse();
  },
};

const RequestLog = {
  process(handlerInput) {
    console.log(`REQUEST ENVELOPE = ${JSON.stringify(handlerInput.requestEnvelope)}`);
  },
};

const ResponseLog = {
  process(handlerInput) {
    console.log(`RESPONSE BUILDER = ${JSON.stringify(handlerInput)}`);
  },
};

const skillBuilder = Alexa.SkillBuilders.custom();

exports.handler = skillBuilder
  .addRequestHandlers(
    NoExitIntentHandler,
    EnterSkillIntentHandler,
    WantKnowIntentHandler,
    DataCollectionIntentHandler,
    LaunchRequestHandler,
    GreetMeIntentHandler,
    EmailIntentHandler,
    MobileIntentHandler,
    HelpIntentHandler,
    CancelAndStopIntentHandler,
    SessionEndedRequestHandler
  )
  .addRequestInterceptors(RequestLog)
  .addResponseInterceptors(ResponseLog)
  .addErrorHandlers(ErrorHandler)
  .withApiClient(new Alexa.DefaultApiClient())
  .lambda();
