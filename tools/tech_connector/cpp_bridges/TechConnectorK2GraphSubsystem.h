#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphPin.h"
#include "EdGraphSchema_K2.h"
#include "K2Node_Event.h"
#include "K2Node_InputKey.h"
#include "K2Node_CallFunction.h"
#include "K2Node_ExecutionSequence.h"
#include "TechConnectorK2GraphSubsystem.generated.h"

/**
 * UTechConnectorK2GraphSubsystem: Native Unreal C++ K2 Node Graph Auto-Wiring Subsystem.
 * Programmatically constructs and physically links K2 Execution Pins (Exec -> Exec) inside
 * Blueprint EventGraphs and AnimGraphs without relying on clipboard or manual UI steps.
 */
UCLASS(BlueprintType, Blueprintable)
class TECHCONNECTOR_API UTechConnectorK2GraphSubsystem : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Physically places and links Event BeginPlay -> PrintString -> LaunchCharacter execution pins in Blueprint memory.
	 */
	UFUNCTION(BlueprintCallable, Category = "TechConnector|NativeGraphWiring")
	static bool AutoWireBlueprintExecutionPins(UBlueprint* TargetBlueprint, FString InputKeyName, FString OnScreenMessage);

	/**
	 * Physically connects State Machine pose output pin into AnimGraph Output Pose node.
	 */
	UFUNCTION(BlueprintCallable, Category = "TechConnector|NativeGraphWiring")
	static bool AutoWireAnimGraphOutputPose(UAnimBlueprint* TargetAnimBlueprint, FString StateMachineName);
};
