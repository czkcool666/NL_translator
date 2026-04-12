#include "SVF-LLVM/LLVMUtil.h"
#include "SVF-LLVM/SVFIRBuilder.h"
#include "MemoryModel/PointerAnalysisImpl.h"
#include "DDA/ContextDDA.h"
#include "DDA/DDAClient.h"
#include "Util/Options.h"
#include "SVFIR/SVFFileSystem.h"
#include <iostream>
#include <string>
#include <map>
#include <set>
#include <vector>
#include <fstream>
#include <nlohmann/json.hpp>

using namespace llvm;
using namespace std;
using namespace SVF;
std::map<std::string, std::vector<std::string>> irContents;

/// Function parameter alias analysis client
class StructAnalyzer : public DDAClient {
private:
    // Store SVFIR reference
    SVFIR* pag;

    struct NodeInfo {
        NodeID id;
        std::string type;        
        std::string description; 
        bool hasValue;           
        std::string valueName;   
        std::string valueType;   
        int line;
        std::string file_name;    
    };
    struct EdgeInfo {
        NodeID srcId;
        NodeID dstId;
        std::string type;        
        std::string description; 
    };

    struct FunctionInfo {
        std::string functionName;
        std::string sourceFile;
        unsigned startLine;
        unsigned endLine;
    };
    struct StructInfo {
        std::string name;                  
        std::map<unsigned, std::string> fieldNames; 
        std::map<unsigned, std::string> fieldTypes; 
        std::set<unsigned> pointerFields;  

        std::map<unsigned, std::map<NodeID, std::vector<std::vector<NodeID>>>> fieldUsageNodeGroups; 
        std::map<unsigned, bool> fieldNullability; 
        std::map<unsigned, std::string> fieldOwnership; 
        std::map<unsigned, bool> fieldMutable; 
    };
    
    std::map<StructType*, StructInfo> structInfoMap;
    

public:
    StructAnalyzer(SVFIR* p) : DDAClient(p->getModule()), pag(p) {
        collectStructInfo();
    }
    
    virtual ~StructAnalyzer() {}
    
    inline SVFIR* getPAG() const {
        return pag;
    }
    
    void collectStructInfo() {
        std::cout << "Collecting struct information..." << std::endl;
        
        LLVMModuleSet* moduleSet = LLVMModuleSet::getLLVMModuleSet();
        
        std::set<std::string> excludePrefixes = {
            "llvm.", "_IO_", "struct._IO_", "std::", "__", "pthread_", "FILE"
        };
        
        for (u32_t i = 0; i < moduleSet->getModuleNum(); ++i) {
            Module* module = moduleSet->getModule(i);
            
            for (Type* type : module->getIdentifiedStructTypes()) {
                StructType* structType = dyn_cast<StructType>(type);
                if (!structType) continue;
                
                StructInfo structInfo;
                structInfo.name = structType->getName().str();
                
                bool shouldSkip = false;
                for (const auto& prefix : excludePrefixes) {
                    if (structInfo.name.find(prefix) == 0) {
                        shouldSkip = true;
                        break;
                    }
                }
                if (!shouldSkip && (
                    structInfo.name.find("marker") != std::string::npos ||
                    structInfo.name.find("wide_data") != std::string::npos ||
                    structInfo.name.find("codecvt") != std::string::npos)) {
                    shouldSkip = true;
                }
                
                if (shouldSkip) continue;
                
                for (unsigned idx = 0; idx < structType->getNumElements(); ++idx) {
                    Type* elemType = structType->getElementType(idx);
                    std::string elemTypeStr = getTypeString(elemType);
                    
                    structInfo.fieldTypes[idx] = elemTypeStr;
                    
                    if (elemType->isPointerTy()) {
                        structInfo.pointerFields.insert(idx);
                    }
                }
                
                structInfoMap[structType] = structInfo;
            }
        }
        
        std::cout << "Struct information collection completed, found " << structInfoMap.size() << " structs" << std::endl;
    }



    void start_analyzeStructsWithPointerFields(ContextDDA* pta) {
        std::cout << "Analyzing structs with pointer fields..." << std::endl;
        ICFG* icfg = pag->getICFG();
        // icfg->dump("icfg.dot");

        collectStructInfo();
        
        size_t structCount = structInfoMap.size();
        size_t currentStructIndex = 0;
        for (auto& pair : structInfoMap) {
            currentStructIndex++;
            StructType* structType = pair.first;
            StructInfo& structInfo = pair.second;

            if (structInfo.pointerFields.empty()) continue;
            std::cout << "Analyzing struct: " << structInfo.name << std::endl;
            for (unsigned fieldIdx : structInfo.pointerFields) {
                structInfo.fieldNullability[fieldIdx] = true;
                structInfo.fieldOwnership[fieldIdx] = "Borrowed"; 
                
                
                bool isMalloc = isFieldMalloc(structType, fieldIdx);
                if (!isMalloc){
                    bool isFreed = isFieldFreed(structType, fieldIdx);
                    structInfo.fieldOwnership[fieldIdx] = (isFreed ? "Owning" : "Borrowed");
                } else{
                    structInfo.fieldOwnership[fieldIdx] = "Owning";
                }

                std::cout << "  Getting the usage scenario of the structure..." << std::endl;
                std::vector<NodeID> fieldNodes = findStructFieldNodes(structType, fieldIdx);
                
                std::cout << "  fieldNodeGroups..." << std::endl;
                std::map<NodeID, std::vector<std::vector<NodeID>>> fieldNodeGroups;
                for(NodeID fieldNodeId : fieldNodes) {
                    std::vector<std::vector<NodeID>> inEdgePaths = getInEdgeNodesWithStore(fieldNodeId);
                    fieldNodeGroups[fieldNodeId] = inEdgePaths;
                }
                structInfo.fieldUsageNodeGroups[fieldIdx] = fieldNodeGroups;
                
                std::cout << "  Analyzing the mutability of the field..." << std::endl;
                structInfo.fieldMutable[fieldIdx] = false; 
                if (structInfo.fieldOwnership[fieldIdx] == "Borrowed") { 
                    structInfo.fieldMutable[fieldIdx] = analyzeFieldMutability(structType, fieldIdx, fieldNodes);
                }

            }
        }
    }


    bool analyzeFieldMutability(StructType* structType, unsigned fieldIdx, const std::vector<NodeID>& fieldNodes) {
        
        std::cout << "  Analyzing the mutability of the field..." << std::endl;
        bool isMutable = false;
        
        for (NodeID fieldNodeId : fieldNodes) {
            if (hasModificationEvidence(fieldNodeId)) {
                isMutable = true;
                break;
            }
        }
        
        return isMutable;
    }


    bool hasModificationEvidence(NodeID nodeId) {
        const PAGNode* node = pag->getGNode(nodeId);
        if (!node) return false;
        
        for (const PAGEdge* edge : node->getOutEdges()) {
            if (edge->getEdgeKind() == PAGEdge::Store) return true;
        }
        
        for (const PAGEdge* edge : node->getOutEdges()) {
            if (edge->getEdgeKind() == PAGEdge::Load) {
                NodeID loadedNodeId = edge->getDstID();
                if (hasModificationAfterLoad(loadedNodeId)) return true;
            }
        }
        
        if (isPassedToModifyingFunction(nodeId)) return true;
        
        return false;
    }

    bool hasModificationAfterLoad(NodeID loadedNodeId) {
        const PAGNode* loadedNode = pag->getGNode(loadedNodeId);
        if (!loadedNode) return false;
        
        std::set<NodeID> visited;
        std::queue<NodeID> worklist;
        
        worklist.push(loadedNodeId);
        visited.insert(loadedNodeId);
        
        while (!worklist.empty()) {
            NodeID currentId = worklist.front();
            worklist.pop();
            
            const PAGNode* currentNode = pag->getGNode(currentId);
            if (!currentNode) continue;
            
            for (const PAGEdge* edge : currentNode->getOutEdges()) {
                if (edge->getEdgeKind() == PAGEdge::Store) {
                    return true;
                }
                
                NodeID dstId = edge->getDstID();
                if (visited.find(dstId) == visited.end()) {
                    visited.insert(dstId);
                    worklist.push(dstId);
                }
            }
        }
        
        return false;
    }
        
    bool isPassedToModifyingFunction(NodeID nodeId) {
        
        bool isPassedToModifying = false;
        
        for (SVFStmt::PEDGEK kind = SVFStmt::Addr; kind <= SVFStmt::ThreadJoin; kind = (SVFStmt::PEDGEK)(kind + 1)) {
            for (const SVFStmt* stmt : pag->getSVFStmtSet(kind)) {
                if (!stmt) continue;
                
                std::string stmtStr = stmt->toString();
                
                if (!isCallToModifyingFunction(stmtStr)) continue;
                
                if (kind == SVFStmt::Call) {
                    const CallPE* callStmt = SVFUtil::dyn_cast<CallPE>(stmt);
                    if (!callStmt) continue;
                    NodeID argNodeID = callStmt->getRHSVarID(); 
                    std::set<NodeID> visited;
                    std::queue<NodeID> worklist;
                    
                    worklist.push(nodeId);
                    visited.insert(nodeId);
                    
                    while (!worklist.empty()) {
                        NodeID currentID = worklist.front();
                        worklist.pop();
                    
                        if (currentID == argNodeID) {
                            isPassedToModifying = true;
                            break;
                        }
                        
                        const PAGNode* node = pag->getGNode(currentID);
                        if (!node) continue;
                        
                        for (const PAGEdge* edge : node->getOutEdges()) {
                            NodeID dstID = edge->getDstID();
                            
                            if (const LoadStmt* load = SVFUtil::dyn_cast<LoadStmt>(edge)) {
                                if (visited.find(dstID) == visited.end()) {
                                    worklist.push(dstID);
                                    visited.insert(dstID);
                                }
                            }
                            else if (const CopyStmt* copy = SVFUtil::dyn_cast<CopyStmt>(edge)) {
                                
                                if (visited.find(dstID) == visited.end()) {
                                    worklist.push(dstID);
                                    visited.insert(dstID);
                                }
                            }
                            else if (const GepStmt* gep = SVFUtil::dyn_cast<GepStmt>(edge)) {
                                if (visited.find(dstID) == visited.end()) {
                                    worklist.push(dstID);
                                    visited.insert(dstID);
                                }
                            }
                        }
                        
                        if (isPassedToModifying) break; 
                    }
                }
                
                if (isPassedToModifying) break; 
            }
            
            if (isPassedToModifying) break; 
        }
        
        return isPassedToModifying;
    }

    bool isCallToModifyingFunction(const std::string& callStr) {
        if (callStr.find("call") == std::string::npos) {
            return false;
        }
        
        static const std::vector<std::string> modifyingFunctionNames = {
            "@strcpy", "@strcat", "@strncpy", "@strncat",
            "@sprintf", "@snprintf", "@memset", "@memcpy", 
            "@memmove", "@scanf", "@gets", "@fgets", 
            "@strtok", "@strtok_r"
        };
        
        for (const auto& funcName : modifyingFunctionNames) {
            if (callStr.find(funcName) != std::string::npos) {
                return true;
            }
        }
        
        return false;
    }



    std::vector<NodeID> findStructFieldNodes(StructType* structType, unsigned fieldIdx, size_t maxNodes = 2) {
        std::vector<NodeID> fieldNodes;
        std::string structTypeName = structType->getName().str();
        
        
        for (auto nodeIt = pag->begin(); nodeIt != pag->end(); ++nodeIt) {
            if (fieldNodes.size() >= maxNodes) break;
            
            NodeID nodeId = nodeIt->first;
            const PAGNode* node = nodeIt->second;
            if (!node) continue;
            
            bool isGepNode = false;
            if (SVFUtil::isa<GepObjVar>(node) || SVFUtil::isa<GepValVar>(node)) {
                isGepNode = true;
            }
            
            std::string nodeStr = node->toString();
            if (nodeStr.find("getelementptr") != std::string::npos) {
                if (nodeStr.find(structTypeName) != std::string::npos) {
                    
                    size_t lastI32Pos = nodeStr.rfind("i32 ");
                    if (lastI32Pos != std::string::npos) {
                        size_t numberStart = lastI32Pos + 4; // "i32 " 长度为4
                        size_t numberEnd = nodeStr.find_first_of(" ,)", numberStart);
                        if (numberEnd == std::string::npos) {
                            numberEnd = nodeStr.length();
                        }
                        
                        if (numberStart < nodeStr.length()) {
                            std::string fieldIndexStr = nodeStr.substr(numberStart, numberEnd - numberStart);
                            
                            unsigned extractedFieldIdx = std::stoul(fieldIndexStr);
                            if (extractedFieldIdx == fieldIdx) {
                                if (std::find(fieldNodes.begin(), fieldNodes.end(), nodeId) == fieldNodes.end()) {
                                    fieldNodes.push_back(nodeId);
                                }
                            } 
                        }
                    }
                }
            }
        }

        return fieldNodes;
    }

    bool isFieldMalloc(StructType* structType, unsigned fieldIdx) {
        bool isOwn = false;
        for (SVFStmt::PEDGEK kind = SVFStmt::Addr; kind <= SVFStmt::ThreadJoin; kind = (SVFStmt::PEDGEK)(kind + 1)) {
            for (const SVFStmt* stmt : pag->getSVFStmtSet(kind)) {
                if (!stmt) continue;
                std::string stmtStr = stmt->toString();
                if (!isMemoryAllocationFunction(stmtStr)) continue;

                const AddrStmt* addrStmt = SVFUtil::dyn_cast<AddrStmt>(stmt);
                if (!addrStmt) continue;
                NodeID lhsID = addrStmt->getLHSVarID(); 

                std::set<NodeID> visited;
                std::queue<NodeID> worklist;
                
                worklist.push(lhsID);
                visited.insert(lhsID);

                while (!worklist.empty()) {
                    NodeID currentID = worklist.front();
                    worklist.pop();
                    
                    const PAGNode* node = pag->getGNode(currentID);
                    if (!node) continue;
                    
                    for (const PAGEdge* edge : node->getOutEdges()) {
                        if (const StoreStmt* store = SVFUtil::dyn_cast<StoreStmt>(edge)) {
                            NodeID dstID = store->getLHSVarID();
                            if (isNodeRepresentingStructField(dstID, structType, fieldIdx)) {
                                isOwn = true;
                                break;
                            }
                        }
                        
                        NodeID dstID = edge->getDstID();
                        if (visited.find(dstID) == visited.end()) {
                            worklist.push(dstID);
                            visited.insert(dstID);
                        }
                    }

                if (isOwn) break; 
                }
            }
        }
        return isOwn;
    }

    bool isFieldFreed(StructType* structType, unsigned fieldIdx) {
        bool isFreed = false;
        std::string structTypeName = structType->getName().str();
        for (const auto& [irFile, lines] : irContents) {
            for (size_t i = 0; i < lines.size(); ++i) {
                const std::string& line = lines[i];
                if (line.find("call void @free(") == std::string::npos) continue;
                size_t start = line.find("noundef %") + 8;
                size_t end = line.find(")", start);
                if (start == std::string::npos || end == std::string::npos) continue;

                std::string freedVar = line.substr(start, end - start);
                freedVar = freedVar.substr(0, freedVar.find(" "));

                for (int j = i - 1; j >= 0 && j >= i - 20; --j) { 
                    const std::string& bitcastLine = lines[j];
                    if (bitcastLine.find(freedVar + " = bitcast") == std::string::npos) continue;
                    std::string bitcastCore = extractBitcastCore(bitcastLine);

                    for (SVFStmt::PEDGEK kind = SVFStmt::Addr; kind <= SVFStmt::ThreadJoin; kind = (SVFStmt::PEDGEK)(kind + 1)) {
                        for (const SVFStmt* stmt : pag->getSVFStmtSet(kind)) {
                            if (!stmt) continue;
                            std::string stmtStr = stmt->toString();
                            if (stmtStr.find(bitcastCore) == std::string::npos) continue;
                            const CopyStmt* copyStmt = SVFUtil::dyn_cast<CopyStmt>(stmt);
                            if (!copyStmt) continue;
                            NodeID srcID = copyStmt->getRHSVarID();
                            if (isNodeRepresentingStructField(srcID, structType, fieldIdx)) {
                                isFreed = true;
                                return isFreed;
                            }
                        }
                    }
                }
                
            }
        
        }
        return isFreed;
    }

    bool isMemoryAllocationFunction(const std::string& callStr) {
        static const std::vector<std::string> allocFuncs = {
            "@malloc", "@calloc", "@realloc", "@strdup", "@strndup"
        };
        
        for (const auto& func : allocFuncs) {
            if (callStr.find(func) != std::string::npos) {
                return true;
            }
        }
        return false;
    }

    std::string extractBitcastCore(const std::string& bitcastLine) {
        size_t debugPos = bitcastLine.find("!dbg");
        if (debugPos != std::string::npos) {
            size_t commaPos = bitcastLine.rfind(",", debugPos);
            if (commaPos != std::string::npos) {
                return bitcastLine.substr(0, commaPos);
            }
        }
        return bitcastLine;
    }

    bool isNodeRepresentingStructField(NodeID nodeId, StructType* structType, unsigned fieldIdx) {
        std::set<NodeID> visited;
        std::queue<NodeID> worklist;
        worklist.push(nodeId);
        visited.insert(nodeId);
        
        while (!worklist.empty()) {
            NodeID currentId = worklist.front();
            worklist.pop();
            
            const PAGNode* node = pag->getGNode(currentId);
            if (!node) continue;
            if (node->hasValue()) {
                const SVFValue* val = node->getValue();
                if (val) {
                    const Value* llvmVal = LLVMModuleSet::getLLVMModuleSet()->getLLVMValue(val);
                    if (llvmVal) {
                        if (const GetElementPtrInst* gep = dyn_cast<GetElementPtrInst>(llvmVal)) {
                            Type* srcType = gep->getSourceElementType();
                            if (srcType == structType) {
                                if (gep->getNumIndices() >= 2) {
                                    if (const ConstantInt* idxVal = dyn_cast<ConstantInt>(gep->getOperand(2))) {
                                        if (idxVal->getZExtValue() == fieldIdx) {
                                            return true;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            
            for (const PAGEdge* edge : node->getInEdges()) {
                NodeID srcId = edge->getSrcID();
                if (visited.find(srcId) == visited.end()) {
                    worklist.push(srcId);
                    visited.insert(srcId);
                }
            }
        }
        
        return false;
    }

    NodeInfo getNodeInfo(const PAGNode* node) {
        NodeInfo nodeInfo;
        if (!node) return nodeInfo;
        
        nodeInfo.id = node->getId();
        nodeInfo.description = node->toString();
        nodeInfo.hasValue = node->hasValue();
        nodeInfo.file_name = "";
        nodeInfo.line = -1;
        std::string desc = node->toString();
        size_t lnPos = desc.find("\"ln\": ");
        size_t flPos = desc.find("\"fl\": ");
        size_t filePos = desc.find("\"file\": ");

        if (lnPos != std::string::npos) {
            lnPos += 6;  
            size_t commaPos = desc.find(",", lnPos);
            size_t bracePos = desc.find("}", lnPos);
            size_t endPos = std::min(commaPos != std::string::npos ? commaPos : desc.length(), 
                                    bracePos != std::string::npos ? bracePos : desc.length());
            
            nodeInfo.line = std::stoi(desc.substr(lnPos, endPos - lnPos));
        }
        
        if (flPos != std::string::npos) {
            flPos += 6;  
            if (flPos < desc.length() && desc[flPos] == '\"') {
                flPos++;  
                size_t endQuote = desc.find('\"', flPos);
                if (endQuote != std::string::npos) {
                    nodeInfo.file_name = desc.substr(flPos, endQuote - flPos);
                }
            }
        } else if (filePos != std::string::npos) {
            filePos += 8;  
            if (filePos < desc.length() && desc[filePos] == '\"') {
                filePos++;  
                size_t endQuote = desc.find('\"', filePos);
                if (endQuote != std::string::npos) {
                    nodeInfo.file_name = desc.substr(filePos, endQuote - filePos);
                }
            }
        }

        if (node->hasValue()) {
            const SVFValue* val = node->getValue();
            if (val) {
                const Value* llvmVal = LLVMModuleSet::getLLVMModuleSet()->getLLVMValue(val);
                if (llvmVal) {
                    nodeInfo.valueName = llvmVal->getName().str();
                }
            }
        }
        
        return nodeInfo;
    }


    FunctionInfo getFunctionInfo(const SVFFunction* func) {
        std::cout << "getFunctionInfo" << std::endl;
        FunctionInfo info;
        info.functionName = func->getName();
        info.sourceFile = "";
        info.startLine = 0;
        info.endLine = 0;
        
        const Value* llvmFunc = LLVMModuleSet::getLLVMModuleSet()->getLLVMValue(func);
        if (const Function* F = dyn_cast<Function>(llvmFunc)) {
            if (F->getSubprogram()) {
                DISubprogram* SP = F->getSubprogram();
                info.sourceFile = SP->getFilename().str();
                info.startLine = SP->getLine();
                
                info.endLine = 0;
                for (const BasicBlock &BB : *F) {
                    for (const Instruction &I : BB) {
                        if (const DebugLoc &DL = I.getDebugLoc()) {
                            if (DL.getLine() > info.endLine) {
                                info.endLine = DL.getLine();
                            }
                        }
                    }
                }
                
                if (info.endLine == 0) {
                    info.endLine = info.startLine;
                }
            } else {
                const Module* M = F->getParent();
                if (M) {
                    info.sourceFile = M->getSourceFileName();
                }
            }
        }
        
        return info;
    }

    std::vector<std::vector<NodeID>> getOutEdges(NodeID nodeId) {
        const PAGNode* startNode = pag->getGNode(nodeId);
        if (!startNode) return {};

        std::map<NodeID, NodeInfo> nodes;
        std::map<NodeID, std::vector<NodeID>> pathGraph;
        NodeInfo startNodeInfo = getNodeInfo(startNode);
        nodes[nodeId] = startNodeInfo;
        std::queue<NodeID> worklist;
        std::set<NodeID> visited;
        
        worklist.push(nodeId);
        visited.insert(nodeId);

        while (!worklist.empty()) {
            NodeID curId = worklist.front();
            worklist.pop();
            
            const PAGNode* curNode = pag->getGNode(curId);
            if (!curNode) continue;
            
            
            for (const PAGEdge* edge : curNode->getOutEdges()) {
                NodeID dstId = edge->getDstID();
                
                
                const PAGNode* dstNode = pag->getGNode(dstId);
                if (!dstNode) continue;
                
                NodeInfo dstNodeInfo = getNodeInfo(dstNode);
                int dstNodeLine = dstNodeInfo.line;
                
                
                nodes[dstId] = dstNodeInfo;
                
                
                pathGraph[curId].push_back(dstId);
                
                if (visited.find(dstId) == visited.end()) {
                    visited.insert(dstId);
                    worklist.push(dstId);
                }
            }
        }
        
        std::vector<std::vector<NodeID>> allPaths;
        std::vector<NodeID> currentPath;
        std::set<NodeID> onPath;
        std::set<NodeID> leafNodes;
        for (const auto& nodePair : nodes) {
            NodeID id = nodePair.first;
            if (pathGraph.find(id) == pathGraph.end() || pathGraph[id].empty()) {
                leafNodes.insert(id);
            }
        }
        if (leafNodes.empty()) {
            for (const auto& nodePair : nodes) {
                if (nodePair.first != nodeId) {  
                    leafNodes.insert(nodePair.first);
                }
            }
        }

        std::function<void(NodeID)> pathDfs = [&](NodeID node) {
            currentPath.push_back(node);
            onPath.insert(node);
            
            if (leafNodes.find(node) != leafNodes.end()) {
                if (currentPath.size() > 1) {
                    allPaths.push_back(currentPath);
                }
            }
            
            if (pathGraph.find(node) != pathGraph.end()) {
                for (NodeID nextNode : pathGraph[node]) {
                    if (onPath.find(nextNode) == onPath.end()) {
                        pathDfs(nextNode);
                    }
                }
            }
            
            currentPath.pop_back();
            onPath.erase(node);
        };
        pathDfs(nodeId);
        return allPaths;
    }



    std::vector<std::vector<NodeID>> getInEdgeNodesWithStore(NodeID nodeId, size_t maxPaths = 2) {
        const PAGNode* startNode = pag->getGNode(nodeId);
        if (!startNode) return {};
        std::vector<NodeID> storeSourceNodes;
        for (const PAGEdge* edge : startNode->getInEdges()) {
            if (edge->getEdgeKind() == PAGEdge::Store) {
                NodeID srcId = edge->getSrcID();
                const PAGNode* srcNode = pag->getGNode(srcId);
                if (srcNode) {
                    storeSourceNodes.push_back(srcId);
                }
            }
        }
        
        if (storeSourceNodes.empty()) return {};
        
        std::map<NodeID, NodeInfo> reverseNodes;
        std::map<std::pair<NodeID, NodeID>, EdgeInfo> reverseEdges;
        
        NodeInfo startNodeInfo = getNodeInfo(startNode);
        reverseNodes[nodeId] = startNodeInfo;
        
        for (NodeID storeNode : storeSourceNodes) {
            EdgeInfo storeEdgeInfo;
            storeEdgeInfo.srcId = storeNode;
            storeEdgeInfo.dstId = nodeId;
            storeEdgeInfo.type = "Store";
            storeEdgeInfo.description = "Store edge";
            reverseEdges[{storeNode, nodeId}] = storeEdgeInfo;
        }
        
        std::set<NodeID> visited;
        std::queue<NodeID> worklist;
        
        for (NodeID storeNode : storeSourceNodes) {
            worklist.push(storeNode);
            visited.insert(storeNode);
            
            const PAGNode* storeSourceNode = pag->getGNode(storeNode);
            if (storeSourceNode) {
                NodeInfo storeNodeInfo = getNodeInfo(storeSourceNode);
                reverseNodes[storeNode] = storeNodeInfo;
            }
        }
        
        while (!worklist.empty()) {
            NodeID curId = worklist.front();
            worklist.pop();
            
            const PAGNode* curNode = pag->getGNode(curId);
            if (!curNode) continue;
            
            for (const PAGEdge* edge : curNode->getInEdges()) {
                NodeID srcId = edge->getSrcID();
                std::string edgeTypeStr = getEdgeTypeStr(edge);
                
                const PAGNode* srcNode = pag->getGNode(srcId);
                if (!srcNode) continue;
                
                NodeInfo srcNodeInfo = getNodeInfo(srcNode);
                
                EdgeInfo edgeInfo;
                edgeInfo.srcId = srcId;
                edgeInfo.dstId = curId;
                edgeInfo.type = edgeTypeStr;
                edgeInfo.description = edge->toString();
                reverseEdges[{srcId, curId}] = edgeInfo;
                
                reverseNodes[srcId] = srcNodeInfo;
                
                if (visited.find(srcId) == visited.end()) {
                    visited.insert(srcId);
                    worklist.push(srcId);
                }
            }
        }
        
        std::map<NodeID, std::vector<NodeID>> pathGraph;
        for (const auto& edgePair : reverseEdges) {
            NodeID src = edgePair.first.first;
            NodeID dst = edgePair.first.second;
            pathGraph[src].push_back(dst);
        }
        
        std::vector<std::vector<NodeID>> allPaths;
        std::vector<NodeID> currentPath;
        std::set<NodeID> onPath;
        
        std::set<NodeID> leafNodes;
        for (const auto& nodePair : reverseNodes) {
            NodeID id = nodePair.first;
            bool hasInEdge = false;
            
            for (const auto& edgePair : reverseEdges) {
                if (edgePair.first.second == id && edgePair.first.first != id) {
                    hasInEdge = true;
                    break;
                }
            }
            
            if (!hasInEdge && id != nodeId) { 
                leafNodes.insert(id);
            }
        }
        
        std::function<void(NodeID)> pathDfs = [&](NodeID node) {
            currentPath.push_back(node);
            onPath.insert(node);
            
            if (node == nodeId) {
                allPaths.push_back(currentPath);
            } else {
                if (pathGraph.find(node) != pathGraph.end()) {
                    for (NodeID nextNode : pathGraph[node]) {
                        if (onPath.find(nextNode) == onPath.end()) {
                            pathDfs(nextNode);
                        }
                    }
                }
            }
            
            currentPath.pop_back();
            onPath.erase(node);
        };
        
        for (NodeID leafNode : leafNodes) {
            currentPath.clear();
            onPath.clear();
            pathDfs(leafNode);
        }
        
        if (allPaths.size() >= maxPaths) {
            allPaths.resize(maxPaths);
        }

        if (allPaths.empty()) {
            for (NodeID storeNode : storeSourceNodes) {
                if (allPaths.size() >= maxPaths) break;
                std::vector<NodeID> simplePath = {storeNode, nodeId};
                allPaths.push_back(simplePath);
            }
        }
        
        return allPaths;
    }


    std::vector<NodeID> getInEdgeNodes(NodeID nodeId) {
        const PAGNode* startNode = pag->getGNode(nodeId);
        if (!startNode) return {};
        std::vector<NodeID> inEdgeNodes;
        std::set<NodeID> visited;
        std::queue<NodeID> worklist;
        
        worklist.push(nodeId);
        visited.insert(nodeId);
        
        while (!worklist.empty()) {
            NodeID curId = worklist.front();
            worklist.pop();
            
            const PAGNode* curNode = pag->getGNode(curId);
            if (!curNode) continue;
            
            for (const PAGEdge* edge : curNode->getInEdges()) {
                NodeID srcId = edge->getSrcID();
                
                const PAGNode* srcNode = pag->getGNode(srcId);
                if (!srcNode) continue;
                
                NodeInfo srcNodeInfo = getNodeInfo(srcNode);
                if (std::find(inEdgeNodes.begin(), inEdgeNodes.end(), srcId) == inEdgeNodes.end()) {
                    inEdgeNodes.push_back(srcId);
                }
                if (visited.find(srcId) == visited.end()) {
                    visited.insert(srcId);
                    worklist.push(srcId);
                }
            }
        }
        return inEdgeNodes;
    }


    std::string getTypeString(Type* type) {
        if (!type) return "null";
        if (type->isIntegerTy()) {
            return "i" + std::to_string(type->getIntegerBitWidth());
        } else if (type->isFloatTy()) {
            return "float";
        } else if (type->isDoubleTy()) {
            return "double";
        } else if (type->isPointerTy()) {
            Type* elemType = type->getPointerElementType();
            return getTypeString(elemType) + "*";
        } else if (type->isArrayTy()) {
            Type* elemType = type->getArrayElementType();
            uint64_t numElements = type->getArrayNumElements();
            return "[" + std::to_string(numElements) + " x " + getTypeString(elemType) + "]";
        } else if (type->isStructTy()) {
            StructType* structType = dyn_cast<StructType>(type);
            if (structType->hasName()) {
                return structType->getName().str();
            } else {
                return "anonymous_struct";
            }
        } else if (type->isFunctionTy()) {
            return "function";
        } else if (type->isVoidTy()) {
            return "void";
        } else {
            return "unknown_type";
        }
    }

    std::string getEdgeTypeStr(const PAGEdge* edge) {
        if (!edge) return "NULL";
        
        switch (edge->getEdgeKind()) {
            case PAGEdge::Addr:      return "Addr";
            case PAGEdge::Copy:      return "Copy";
            case PAGEdge::Store:     return "Store";
            case PAGEdge::Load:      return "Load";
            case PAGEdge::Call:      return "Call";
            case PAGEdge::Ret:       return "Ret";
            case PAGEdge::Gep:       return "Gep";
            case PAGEdge::ThreadFork:return "ThreadFork";
            case PAGEdge::ThreadJoin:return "ThreadJoin";
            default:                 return "Unknown";
        }
    }

    void generateAnalysisReport(const std::string& outputFile) {
        nlohmann::json reportJson;
        
        for (const auto& structPair : structInfoMap) {
            StructType* structType = structPair.first;
            const StructInfo& structInfo = structPair.second;
            
            nlohmann::json structJson;
            
            nlohmann::json fieldsArrayJson = nlohmann::json::array();
            
            for (const auto& fieldTypePair : structInfo.fieldTypes) {
                unsigned fieldIdx = fieldTypePair.first;
                const std::string& fieldType = fieldTypePair.second;
                
                nlohmann::json fieldJson;
                fieldJson["field_index"] = fieldIdx;
                fieldJson["field_type"] = fieldType;
                fieldJson["is_pointer"] = (structInfo.pointerFields.find(fieldIdx) != structInfo.pointerFields.end());
                
                auto fieldNameIt = structInfo.fieldNames.find(fieldIdx);
                if (fieldNameIt != structInfo.fieldNames.end()) {
                    fieldJson["field_name"] = fieldNameIt->second;
                } else {
                    fieldJson["field_name"] = "field_" + std::to_string(fieldIdx);
                }
                
                if (structInfo.pointerFields.find(fieldIdx) != structInfo.pointerFields.end()) {
                    auto nullabilityIt = structInfo.fieldNullability.find(fieldIdx);
                    if (nullabilityIt != structInfo.fieldNullability.end()) {
                        fieldJson["nullability"] = nullabilityIt->second ? "Nullable" : "Not_nullable";
                    } else {
                        fieldJson["nullability"] = "Unknown";
                    }
                    auto ownershipIt = structInfo.fieldOwnership.find(fieldIdx);
                    if (ownershipIt != structInfo.fieldOwnership.end()) {
                        fieldJson["ownership"] = ownershipIt->second;
                    } else {
                        fieldJson["ownership"] = "Unknown";
                    }
                    
                    auto mutableIt = structInfo.fieldMutable.find(fieldIdx);
                    if (mutableIt != structInfo.fieldMutable.end()) {
                        fieldJson["mutability"] = mutableIt->second ? "Mutable" : "Immutable";
                    } else {
                        fieldJson["mutability"] = "Unknown";
                    }
                }
                
                fieldsArrayJson.push_back(fieldJson);
            }
            structJson["fields"] = fieldsArrayJson;
            
            nlohmann::json usagePathsJson;
            for (const auto& fieldUsageGroupPair : structInfo.fieldUsageNodeGroups) {
                unsigned fieldIdx = fieldUsageGroupPair.first;
                const std::map<NodeID, std::vector<std::vector<NodeID>>>& fieldNodeGroups = fieldUsageGroupPair.second;
                
                std::string fieldKey = "field_" + std::to_string(fieldIdx);
                nlohmann::json fieldPathsArrayJson = nlohmann::json::array();
                
                for (const auto& groupPair : fieldNodeGroups) {
                    NodeID fieldNodeId = groupPair.first;
                    const std::vector<std::vector<NodeID>>& pathsList = groupPair.second;
                    
                    nlohmann::json fieldNodeGroupJson;
                    fieldNodeGroupJson["field_node_id"] = fieldNodeId;
                    
                    const PAGNode* fieldNode = pag->getGNode(fieldNodeId);
                    if (fieldNode) {
                        NodeInfo fieldNodeInfo = getNodeInfo(fieldNode);
                        std::string fieldLocation;
                        if (!fieldNodeInfo.file_name.empty() && fieldNodeInfo.line > 0) {
                            fieldLocation = fieldNodeInfo.file_name + ":" + std::to_string(fieldNodeInfo.line);
                            fieldNodeGroupJson["field_node_location"] = fieldLocation;
                        }                         
                    }
                
                    nlohmann::json pathsArrayJson = nlohmann::json::array();
                    
                    for (size_t pathIdx = 0; pathIdx < pathsList.size(); pathIdx++) {
                        const std::vector<NodeID>& singlePath = pathsList[pathIdx];
                        
                        if (!singlePath.empty()) {
                            std::vector<std::string> locationPath;
                            
                            for (NodeID nodeId : singlePath) {
                                const PAGNode* node = pag->getGNode(nodeId);
                                if (!node) continue;
                                
                                NodeInfo nodeInfo = getNodeInfo(node);
                                
                                std::string location;
                                if (!nodeInfo.file_name.empty() && nodeInfo.line > 0) {
                                    location = nodeInfo.file_name + ":" + std::to_string(nodeInfo.line);
                                    locationPath.push_back(location);
                                } 
                            }
                            
                            std::vector<std::string> deduplicatedPath;
                            std::string lastLocation = "";
                            
                            for (const std::string& location : locationPath) {
                                if (location != lastLocation) {
                                    deduplicatedPath.push_back(location);
                                    lastLocation = location;
                                }
                            }
                            
                            nlohmann::json singlePathJson = nlohmann::json::array();
                            for (const std::string& location : deduplicatedPath) {
                                singlePathJson.push_back(location);
                            }
                            
                            if (!singlePathJson.empty()) {
                                pathsArrayJson.push_back(singlePathJson);
                            }
                        }
                    }
                    
                    fieldNodeGroupJson["paths"] = pathsArrayJson;
                    fieldNodeGroupJson["path_count"] = pathsArrayJson.size();
                    
                    if (!pathsArrayJson.empty()) {
                        fieldPathsArrayJson.push_back(fieldNodeGroupJson);
                    }
                }
                
                if (!fieldPathsArrayJson.empty()) {
                    usagePathsJson[fieldKey] = fieldPathsArrayJson;
                }
            }
            
            structJson["usage_paths"] = usagePathsJson;
            reportJson[structInfo.name] = structJson;
        }
        
        std::ofstream outFile(outputFile);
        if (!outFile.is_open()) {
            return;
        }
        
        outFile << reportJson.dump(4) << std::endl;
        outFile.close();
    }
};



int main(int argc, char** argv) {
    std::cout << "SVF Struct Analysis Start" << std::endl;
    

    std::vector<std::string> irFiles;
    for (int i = 1; i < argc; ++i) {
        irFiles.emplace_back(argv[i]);
    }
    
    for (const std::string& irFile : irFiles) {
        std::ifstream inFile(irFile);
        std::vector<std::string> lines;
        std::string line;
        while (std::getline(inFile, line)) {
            lines.push_back(line);
        }
        inFile.close();
        irContents[irFile] = lines;
    }

    std::cout << "Initializing SVF..." << std::endl;
    
    SVFModule* svfModule = LLVMModuleSet::getLLVMModuleSet()->buildSVFModule(irFiles);

    std::cout << "Building SVFIR..." << std::endl;
    SVFIRBuilder builder(svfModule);
    SVFIR* pag = builder.build();
    
    StructAnalyzer* analyzer = new StructAnalyzer(pag);
    
    /// Create context-sensitive pointer analysis
    std::cout << "Executing Context-Sensitive Pointer Analysis..." << std::endl;
    ContextDDA* pta = new ContextDDA(pag, analyzer);
    pta->initialize();
    
    /// Analyze structs with pointer fields
    std::cout << "Analyzing structs with pointer fields..." << std::endl;
    analyzer->start_analyzeStructsWithPointerFields(pta);

    std::string outputFile = "struct_analysis_report.json";
    analyzer->generateAnalysisReport(outputFile);
    
    /// Cleanup
    delete analyzer;
    delete pta;
    SVFIR::releaseSVFIR();
    LLVMModuleSet::releaseLLVMModuleSet();
    
    std::cout << "Struct Analysis Completed." << std::endl;
    return 0;
}