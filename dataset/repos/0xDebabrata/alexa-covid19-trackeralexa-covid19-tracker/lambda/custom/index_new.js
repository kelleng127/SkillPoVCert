/* eslint-disable  func-names */
/* eslint-disable  no-console */

const Alexa = require('ask-sdk');
const dbHelper = require('./helpers/dbHelper');
const GENERAL_REPROMPT = "What would you like to do?";
const dynamoDBTableName = "CoronaData";

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
    const speakOutput = 'This skill will collect your name during the conversation. Please say yes to continue or no to exit.';
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
    const speakOutput = 'This skill will collect your name during the conversation. Please respond to any pending questions to continue, or say no if you wish to end the session.';
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
    const speechText = 'Welcome to corona update.';

    return handlerInput.responseBuilder
      .speak(speechText)
      .reprompt('How can I help?')
      .getResponse();
  },
};

const getCoronaUpdateHandler = {
  canHandle(handlerInput) {
    return handlerInput.requestEnvelope.request.type === 'IntentRequest'
      && handlerInput.requestEnvelope.request.intent.name === 'getCoronaUpdate';
  },
  async handle(handlerInput) {
    const { responseBuilder } = handlerInput;
    let country = handlerInput.requestEnvelope.request.intent.slots.country.value;
    country = country.toLowerCase();
    function capitalizeFirstLetter(string) {
      return string.charAt(0).toUpperCase() + string.slice(1);
    }
    if (country === 'usa' || country === 'america' || country === 'us'){
      country = 'USA';
    } else if (country === 'england' || country === 'uk'){
      country = 'UK'
    } else {
      country = capitalizeFirstLetter(country);
    }

    return dbHelper.getData(country)
      .then((data) => {
        var speechText = "";
        if (data.length == 0) {
          speechText = "Sorry. I could not find the required information. Please try again"
        } else {
          if (data[0].deaths === 'Not available'){
            speechText += 'There have been a total of ' + data[0].totalCases + ' coronavirus related cases in ' + data[0].country + '. The number of coronavirus related deaths are unavailable';
          } else {
            speechText += 'There have been a total of ' + data[0].totalCases + ' coronavirus related cases in ' + data[0].country + '. ' + data[0].deaths + ' people have died.';
          }
        }
        return responseBuilder
          .speak(speechText)
          .reprompt(GENERAL_REPROMPT)
          .getResponse();
      })
      .catch((err) => {
        const speechText = "Sorry, I cannot get the data right now. Try again!";
        return responseBuilder
          .speak(speechText)
          .getResponse();
      })
  }
}

const HelpIntentHandler = {
  canHandle(handlerInput) {
    return handlerInput.requestEnvelope.request.type === 'IntentRequest'
      && handlerInput.requestEnvelope.request.intent.name === 'AMAZON.HelpIntent';
  },
  handle(handlerInput) {
    const speechText = 'You can introduce yourself by telling me your name';

    return handlerInput.responseBuilder
      .speak(speechText)
      .reprompt(speechText)
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

const skillBuilder = Alexa.SkillBuilders.standard();

exports.handler = skillBuilder
  .addRequestHandlers(
    NoExitIntentHandler,
    EnterSkillIntentHandler,
    WantKnowIntentHandler,
    DataCollectionIntentHandler,
    getCoronaUpdateHandler,
    LaunchRequestHandler,
    HelpIntentHandler,
    CancelAndStopIntentHandler,
    SessionEndedRequestHandler
  )
  .addErrorHandlers(ErrorHandler)
  .withTableName(dynamoDBTableName)
  .withAutoCreateTable(true)
  .lambda();
